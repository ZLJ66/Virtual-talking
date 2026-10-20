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
  /**
   * 是否已错过主线截止时间。
   *
   * 单向标记：一旦越过截止就保持为 true。设计文档 5.4 规定
   * 错过不中断游戏、不显示失败，只是世界记住这件事——
   * 注册处开始要求说明原因，玩家多出一条「解释与请求通融」的路。
   */
  mainline_missed?: boolean
}

/**
 * 主线进度快照。
 *
 * 由后端 mainline.py 计算，前端只负责显示——
 * 「什么算能办」的规则只能有一份实现，两边各写一遍必然漂移。
 */
export interface MainlineProgress {
  title: string
  deadline: { day?: number; slot?: string } | null
  missed: boolean
  total: number
  done: number
  done_titles: string[]
  pending_titles: string[]
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
  /** 起始时刻的主线判定结果（人话），后端已算好 */
  mainline_lines?: string[]
  progress?: MainlineProgress
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
  /** 这次移动/等待是否刚好越过了主线截止时间 */
  mainline_just_missed?: boolean
  mainline_lines?: string[]
  progress?: MainlineProgress
}

/** 判定器对 AI 提议的裁决结果 */
export interface JudgeResult {
  player_state: PlayerState
  /** 被接受的变更，中文描述 */
  applied: string[]
  /** 被拒绝的变更，含人话原因 */
  rejected: string[]
  /** 本回合新完成的主线节点 id */
  completed: string[]
  just_missed: boolean
  mainline_lines: string[]
  progress: MainlineProgress
  /** 给玩家看的一句话，空字符串表示没什么要说的 */
  notice: string
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
