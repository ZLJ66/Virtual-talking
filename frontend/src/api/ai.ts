// 后端 AI API 调用层
// 所有 AI 请求通过本地 FastAPI 后端代理，API 密钥不暴露给客户端
//
// 阶段 A 变更：请求参数由「场景卡」改为「世界状态 + 地点卡 + NPC 卡」，
// 使 AI 能拿到真实的具体信息（感官细节、NPC 性格、印象标签），
// 而非抽象的场景名——这是消除套路感的根本。

import type { CharacterProfile } from '../types'
import type {
  PlayerState,
  WorldLocation,
  WorldNPC,
  WorldResponse,
} from '../types/world'

const API_BASE = 'http://localhost:8000'

export interface AITurnResponse {
  narration: { en: string; zh: string }
  npc: { speaker_id: string; speaker_name: string; content: string }
  feedback: {
    understood: boolean
    naturalness: 'good' | 'ok' | 'needs_improvement'
    naturalness_note: string
    appropriateness: 'good' | 'ok' | 'needs_improvement'
    appropriateness_note: string
    suggested_expression: string
    suggestion_reason: string
  } | null
  completes_scene: boolean
  world_changes: {
    set_fact?: Record<string, boolean>
    add_item?: string
    /** AI 提议：某 NPC 开始跟随玩家 */
    add_companion?: string
    /** AI 提议：某 NPC 不再跟随 */
    remove_companion?: string
    set_location?: string
    set_time?: unknown
    [key: string]: unknown
  }
}

export interface AIOpeningResponse {
  narration: { en: string; zh: string }
  npc: { speaker_id: string; speaker_name: string; content: string }
  feedback: null
  completes_scene: boolean
  world_changes: Record<string, unknown>
}

/** 构造对话历史（从事件列表提取最近几轮） */
export function buildHistory(
  events: {
    kind: string
    content?: string
    speech?: string
    action?: string
    zh?: string
    en?: string
    speakerName?: string
    title?: string
  }[],
): { role: string; content: string }[] {
  const history: { role: string; content: string }[] = []
  for (const ev of events) {
    switch (ev.kind) {
      case 'narration':
      case 'action_result':
        history.push({ role: 'narration', content: ev.en || ev.zh || '' })
        break
      case 'npc_dialogue':
        history.push({ role: 'npc', content: ev.content || '' })
        break
      case 'player_input': {
        const text = [ev.speech, ev.action].filter(Boolean).join(' / ')
        if (text) history.push({ role: 'player', content: text })
        break
      }
      case 'scene_intro':
        history.push({ role: 'narration', content: `[到达 ${ev.title ?? ''}]` })
        break
    }
  }
  return history.slice(-8)
}

/** 地点卡 → 后端需要的结构 */
export function locationToAPI(loc: WorldLocation, slot?: string) {
  return {
    id: loc.id,
    name: loc.name,
    name_en: loc.name_en,
    sensory: loc.sensory,
    variant: slot ? ((loc.variants as Record<string, string>)[slot] ?? '') : '',
    open_hours: loc.open_hours,
    resident_npcs: loc.resident_npcs,
  }
}

/** NPC 卡 → 后端需要的结构（含印象标签与记忆） */
export function npcToAPI(
  npc: WorldNPC | undefined,
  player: PlayerState | null,
  isCompanion = false,
) {
  if (!npc) return null
  const state = player?.npc_states?.[npc.id]
  return {
    id: npc.id,
    name: npc.name,
    role: npc.role,
    age: npc.age,
    background: npc.background,
    personality: npc.personality,
    speech: npc.speech,
    impression_tags: state?.impression_tags ?? [],
    memories: state?.memories ?? [],
    is_companion: isCompanion,
  }
}

/**
 * 组装「在场的人」列表：当地常驻 NPC + 跟随玩家的同伴。
 *
 * 为什么需要这个函数：以前只传一个 npc，所以同行的人到不了 AI 眼里。
 * 现在把所有在场者都传过去，由 AI 决定谁说话。
 */
export function buildPresentNPCs(
  location: WorldLocation | null,
  allNPCs: WorldNPC[],
  player: PlayerState | null,
) {
  if (!location || !player) return []

  const byId = new Map(allNPCs.map((n) => [n.id, n]))
  const present: NonNullable<ReturnType<typeof npcToAPI>>[] = []
  const seen = new Set<string>()

  // 1. 当地常驻 NPC
  for (const id of location.resident_npcs ?? []) {
    const npc = byId.get(id)
    if (!npc || seen.has(id)) continue
    seen.add(id)
    const payload = npcToAPI(npc, player, false)
    if (payload) present.push(payload)
  }

  // 2. 跟随玩家的同伴（即使这个地点不是他的常驻地）
  for (const id of player.companions ?? []) {
    if (seen.has(id)) continue
    const npc = byId.get(id)
    if (!npc) continue
    seen.add(id)
    const payload = npcToAPI(npc, player, true)
    if (payload) present.push(payload)
  }

  return present
}

/** 玩家档案 → 后端结构 */
export function profileToAPI(profile: CharacterProfile) {
  return {
    englishLevel: profile.englishLevel,
    name: profile.name || undefined,
    narrationLanguage: profile.narrationLanguage,
  }
}

/** 世界状态 → 后端结构 */
export function worldStateToAPI(player: PlayerState, world: WorldResponse) {
  return {
    location: player.location,
    time: { day: player.time.day, slot: player.time.slot },
    inventory: player.inventory,
    facts: player.facts,
    knowledge: player.knowledge,
    world_title: world.world.title,
    mainline_title: world.mainline.title,
    deadline: world.mainline.deadline,
    companions: player.companions ?? [],
  }
}

/** 调用 /api/turn 生成一个回合 */
export async function fetchTurn(
  location: WorldLocation,
  allNPCs: WorldNPC[],
  profile: CharacterProfile,
  player: PlayerState,
  world: WorldResponse,
  events: Parameters<typeof buildHistory>[0],
  playerInput: { speech: string; action: string },
): Promise<AITurnResponse> {
  const res = await fetch(`${API_BASE}/api/turn`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      location: locationToAPI(location, player.time.slot),
      npcs: buildPresentNPCs(location, allNPCs, player),
      profile: profileToAPI(profile),
      world_state: worldStateToAPI(player, world),
      world_rules: world.world.rules,
      history: buildHistory(events),
      player_input: playerInput,
    }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`AI turn 请求失败 (${res.status}): ${err}`)
  }
  return res.json() as Promise<AITurnResponse>
}

/** 调用 /api/opening 生成地点开场 */
export async function fetchOpening(
  location: WorldLocation,
  allNPCs: WorldNPC[],
  profile: CharacterProfile,
  player: PlayerState,
  world: WorldResponse,
  recentSummary: string,
): Promise<AIOpeningResponse> {
  const res = await fetch(`${API_BASE}/api/opening`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      location: locationToAPI(location, player.time.slot),
      npcs: buildPresentNPCs(location, allNPCs, player),
      profile: profileToAPI(profile),
      world_state: worldStateToAPI(player, world),
      world_rules: world.world.rules,
      recent_summary: recentSummary,
    }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`AI opening 请求失败 (${res.status}): ${err}`)
  }
  return res.json() as Promise<AIOpeningResponse>
}
