// 世界层类型定义
// 与后端 world_models.py 对应，是前后端的数据合同。
//
// 注意：项目开启 erasableSyntaxOnly，不能使用 enum，统一用字面量联合类型。

/* ----------------------------- 世界静态定义 ----------------------------- */

/** 六时段。不显示具体分钟——有节奏感，但不逼玩家算时间。 */
export type TimeSlot =
  | 'morning'
  | 'forenoon'
  | 'noon'
  | 'afternoon'
  | 'evening'
  | 'night'

export const TIME_SLOT_ORDER: TimeSlot[] = [
  'morning',
  'forenoon',
  'noon',
  'afternoon',
  'evening',
  'night',
]

export const TIME_SLOT_LABELS_ZH: Record<TimeSlot, string> = {
  morning: '早晨',
  forenoon: '上午',
  noon: '中午',
  afternoon: '下午',
  evening: '傍晚',
  night: '晚上',
}

/** 感官细节：生成层具体性的来源，五项全部必填 */
export interface Sensory {
  sight: string
  sound: string
  smell: string
  touch: string
  temperature: string
}

export interface WorldLocation {
  id: string
  name: string
  name_en: string
  open_hours: [number, number]
  travel_cost: number
  connections: string[]
  resident_npcs: string[]
  sensory: Sensory
  variants: Partial<Record<TimeSlot, string>>
  state_fields: Record<string, unknown>
}

export interface NPCSpeech {
  style: string
  accent: string
  catchphrase: string
  tone: string
}

export interface WorldNPC {
  id: string
  name: string
  role: string
  age: number | null
  background: string
  personality: string
  speech: NPCSpeech
}

export interface MainlineNode {
  id: string
  title: string
  location: string
  requires: string[]
  requires_items: string[]
  grants_facts: string[]
}

export interface Mainline {
  title: string
  deadline: { day?: number; slot?: TimeSlot } | null
  nodes: MainlineNode[]
}

export interface WorldMeta {
  country: string
  city: string
  season: string
  weather: string
  currency: string
  language_env: string
  timezone: string
}

export interface WorldRules {
  rules: string[]
  taboos: string[]
}

export interface WorldInfo {
  id: string
  title: string
  year: number
  meta: WorldMeta
  rules: WorldRules
}

/* ----------------------------- 运行时状态 ----------------------------- */

export interface WorldTime {
  day: number
  slot: TimeSlot
}

export interface NPCState {
  impression_tags: string[]
  memories: string[]
}

/**
 * 玩家运行时状态。
 *
 * 注意：这是「世界状态」，不是「游戏进度」。
 * 没有 sceneIndex / stepIndex——进度由 location + time + facts 表达。
 */
export interface PlayerState {
  location: string
  time: WorldTime
  inventory: string[]
  facts: Record<string, boolean>
  knowledge: string[]
  npc_states: Record<string, NPCState>
  /**
   * 跟随玩家移动的 NPC id 列表。
   *
   * 为什么需要：玩家可以邀请 NPC 同行（"一起去逛逛吧"），
   * 若系统不记录，NPC 会在移动后凭空消失——这直接破坏世界一致性。
   */
  companions: string[]
  visit_counts: Record<string, number>
  last_visit: Record<string, WorldTime>
}

/**
 * 当前在场的 NPC（当地常驻 + 同行者）。
 * `is_companion` 用于让 AI 区分"跟着来的人"和"本地人"。
 */
export interface PresentNPC extends WorldNPC {
  is_companion: boolean
}

/* ----------------------------- API 响应 ----------------------------- */

export interface WorldResponse {
  world: WorldInfo
  locations: WorldLocation[]
  npcs: WorldNPC[]
  mainline: Mainline
  facts: Record<string, boolean>
  player_start: PlayerState
}

export interface MoveResult {
  ok: boolean
  reason: string
  player_state: PlayerState | null
  time_narration: string
  location: {
    id: string
    name: string
    name_en: string
    travel_cost: number
    connections: string[]
    resident_npcs: string[]
    sensory: Sensory
    variant: string
    is_open: boolean
  } | null
}

/* ----------------------------- 展示辅助 ----------------------------- */

/** 把时间格式化为「第 N 天 早晨」 */
export function formatTime(t: WorldTime): string {
  return `第 ${t.day} 天 ${TIME_SLOT_LABELS_ZH[t.slot]}`
}

/** 判断某地点在当前时段是否营业（前端预判，最终以后端为准） */
export function isOpenAt(loc: WorldLocation, slot: TimeSlot): boolean {
  const [start, end] = loc.open_hours
  if (start === 0 && end === 24) return true
  const hourMap: Record<TimeSlot, number> = {
    morning: 6,
    forenoon: 9,
    noon: 12,
    afternoon: 14,
    evening: 18,
    night: 21,
  }
  const hour = hourMap[slot]
  return hour >= start && hour < end
}
