// 后端 API 调用层
// 所有 AI 请求通过本地 FastAPI 后端代理，API 密钥不暴露给客户端

import type { CharacterProfile, SceneDef, WorldState } from '../types'

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
    add_item?: string
    set_quest?: { id: string; status: string }
    set_npc?: string
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
export function buildHistory(events: { kind: string; content?: string; speech?: string; zh?: string; en?: string }[]): { role: string; content: string }[] {
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
      case 'player_input':
        if (ev.speech) history.push({ role: 'player', content: ev.speech })
        break
    }
  }
  // 最多保留最近 8 条
  return history.slice(-8)
}

/** 从 SceneDef 构造后端需要的场景对象 */
export function sceneToAPIScene(scene: SceneDef) {
  return {
    title: scene.title,
    description: scene.description,
    goal: scene.goal,
    location: scene.id === 'convenience_store' ? '英国街角便利店'
      : scene.id === 'bus_stop' ? '英国街角公交站'
      : scene.id === 'cafe' ? '英国校园旁咖啡馆'
      : '英国',
    npcs: [{
      id: scene.npcId,
      name: scene.npcName,
      role: '',
      personality: '',
    }],
  }
}

/** 从 CharacterProfile 构造后端需要的 profile 对象 */
export function profileToAPIProfile(profile: CharacterProfile) {
  return {
    englishLevel: profile.englishLevel,
    name: profile.name || undefined,
  }
}

/** 从 WorldState 构造后端需要的世界状态 */
export function worldStateToAPI(ws: WorldState) {
  return {
    inventory: ws.inventory,
    quests: Object.entries(ws.questStatus).map(([id, status]) => ({ id, status })),
    npcStates: {},
  }
}

/** 调用 /api/turn 生成一个回合 */
export async function fetchTurn(
  scene: SceneDef,
  profile: CharacterProfile,
  worldState: WorldState,
  events: { kind: string; content?: string; speech?: string; zh?: string; en?: string }[],
  playerInput: { speech: string; action: string },
): Promise<AITurnResponse> {
  const res = await fetch(`${API_BASE}/api/turn`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      scene: sceneToAPIScene(scene),
      profile: profileToAPIProfile(profile),
      world_state: worldStateToAPI(worldState),
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

/** 调用 /api/opening 生成场景开场 */
export async function fetchOpening(
  scene: SceneDef,
  profile: CharacterProfile,
  prevSceneSummary?: string,
): Promise<AIOpeningResponse> {
  const res = await fetch(`${API_BASE}/api/opening`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      scene: sceneToAPIScene(scene),
      profile: profileToAPIProfile(profile),
      prev_scene_summary: prevSceneSummary,
    }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`AI opening 请求失败 (${res.status}): ${err}`)
  }
  return res.json() as Promise<AIOpeningResponse>
}
