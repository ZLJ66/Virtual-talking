// 游戏状态管理：useReducer + Context
//
// 阶段 A 重写：进度模型由「场景索引」改为「世界状态」。
//   旧：sceneIndex / stepIndex（线性走廊，一个数字表达进度）
//   新：location / time / facts / npc_states（自由移动，状态即进度）
//
// 保留不动的资产：
//   · 事件流 GameEvent[]（唯一真相来源）
//   · 打断 / 暂停 / 请求重复
//   · 双语旁白与语言切换
//   · 反馈记录

import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  useEffect,
  useRef,
  type Dispatch,
  type ReactNode,
} from 'react'

import { fetchTurn, fetchOpening } from '../api/ai'
import type { AITurnResponse, AIOpeningResponse } from '../api/ai'
import { fetchWorld, fetchMove, fetchWait } from '../api/world'
import type {
  CharacterProfile,
  DialogueDisplay,
  ExpressionFeedback,
  GameEvent,
  GamePhase,
  NarrationLanguage,
  PracticeMode,
} from '../types'
import type {
  MoveResult,
  PlayerState,
  WorldLocation,
  WorldResponse,
} from '../types/world'

/* ----------------------------- State ----------------------------- */

export interface GameState {
  phase: GamePhase
  profile: CharacterProfile | null
  mode: PracticeMode
  narrationLang: NarrationLanguage

  // ── 世界静态数据（从后端拉取一次）──
  world: WorldResponse | null
  worldLoading: boolean
  worldError: string | null

  // ── 玩家运行时状态（进度的唯一表达）──
  player: PlayerState | null

  // ── 事件流（唯一真相来源）──
  events: GameEvent[]
  feedbacks: ExpressionFeedback[]

  // ── 对话展示 ──
  dialogue: DialogueDisplay
  awaitingInput: boolean

  // ── 移动 / 等待 ──
  moving: boolean
  moveError: string | null

  // ── AI 调用 ──
  aiLoading: boolean
  aiError: string | null

  // ── 时间流逝叙述 ──
  timeNarration: string
}

const initialState: GameState = {
  phase: 'setup',
  profile: null,
  mode: 'immersive',
  narrationLang: 'both',
  world: null,
  worldLoading: false,
  worldError: null,
  player: null,
  events: [],
  feedbacks: [],
  dialogue: { eventId: null, status: 'idle', repeatToken: 0 },
  awaitingInput: false,
  moving: false,
  moveError: null,
  aiLoading: false,
  aiError: null,
  timeNarration: '',
}

/* ----------------------------- Actions ----------------------------- */

export type GameAction =
  | { type: 'SET_PROFILE'; profile: CharacterProfile }
  | { type: 'SET_MODE'; mode: PracticeMode }
  | { type: 'SET_NARRATION_LANG'; lang: NarrationLanguage }
  | { type: 'WORLD_LOADING' }
  | { type: 'WORLD_LOADED'; world: WorldResponse }
  | { type: 'WORLD_ERROR'; error: string }
  | { type: 'MOVE_START'; target: string }
  | { type: 'MOVE_SUCCESS'; result: MoveResult; target: string }
  | { type: 'MOVE_ERROR'; error: string }
  | { type: 'WAIT_START' }
  | { type: 'WAIT_SUCCESS'; result: MoveResult }
  | { type: 'SUBMIT_INPUT'; speech: string; action: string }
  | { type: 'AI_TURN_SUCCESS'; result: AITurnResponse }
  | { type: 'AI_TURN_ERROR'; error: string }
  | { type: 'AI_OPENING_SUCCESS'; result: AIOpeningResponse; locationId: string }
  | { type: 'AI_OPENING_ERROR'; error: string }
  | { type: 'DIALOGUE_DONE' }
  | { type: 'INTERRUPT' }
  | { type: 'PAUSE' }
  | { type: 'RESUME' }
  | { type: 'REQUEST_REPEAT' }
  | { type: 'RESET' }
  | { type: 'CLEAR_ERROR' }

/* ----------------------------- 辅助函数 ----------------------------- */

let idCounter = 0
function nextId(prefix: string): string {
  idCounter += 1
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`
}

/** 进入地点时追加的事件（不含 AI 生成部分） */
function buildEnterEvents(
  loc: WorldLocation,
  timeNarration: string,
  isFirstVisit: boolean,
): GameEvent[] {
  const events: GameEvent[] = [
    {
      id: nextId('ev'),
      kind: 'scene_intro',
      sceneId: loc.id,
      title: loc.name,
      description: loc.name_en,
    },
  ]

  // 时间流逝叙述（设计文档 4.6：时间必须被叙述，而非 UI 数字跳变）
  if (timeNarration) {
    events.push({ id: nextId('ev'), kind: 'narration', zh: timeNarration, en: '' })
  }

  // 首次进入时展示感官细节（生成层具体性的来源）
  if (isFirstVisit && loc.sensory) {
    const s = loc.sensory
    events.push({
      id: nextId('ev'),
      kind: 'narration',
      zh: `${s.sight}。${s.sound}。`,
      en: '',
    })
  }

  return events
}

/** AI 返回的世界变更（宽松类型，逐项校验后才应用） */
interface AIWorldChanges {
  set_fact?: Record<string, boolean>
  set_facts?: Record<string, boolean>
  add_item?: string
  set_location?: string
  set_time?: unknown
  [key: string]: unknown
}

/**
 * 应用 AI 提议的世界状态变更。
 *
 * **设计约束（世界层设计 5.6）：**
 * AI 返回的 world_changes 只是「提议」，代码校验通过后才生效。
 * 两条最重要的拒绝规则：
 *   1. AI 不得移动玩家
 *   2. AI 不得推进时间
 */
function applyWorldChanges(
  player: PlayerState,
  changes: AIWorldChanges,
  world: WorldResponse | null,
): PlayerState {
  const next: PlayerState = {
    ...player,
    facts: { ...player.facts },
    inventory: [...player.inventory],
  }

  // 明确拒绝：AI 不得移动玩家 / 推进时间
  if ('set_location' in changes || 'set_time' in changes) {
    console.warn('[world] 拒绝 AI 提议的移动或时间推进', {
      set_location: changes.set_location,
      set_time: changes.set_time,
    })
  }

  // 事实变更：必须在白名单内
  const factChanges = changes.set_fact ?? changes.set_facts
  if (factChanges && world) {
    const whitelist = new Set(Object.keys(world.facts))
    for (const [key, value] of Object.entries(factChanges)) {
      if (!whitelist.has(key)) {
        console.warn(`[world] 拒绝未声明的事实: ${key}`)
        continue
      }
      next.facts[key] = value
    }
  }

  // 物品
  if (typeof changes.add_item === 'string' && changes.add_item) {
    if (!next.inventory.includes(changes.add_item)) {
      next.inventory.push(changes.add_item)
    }
  }

  return next
}

/* ----------------------------- Reducer ----------------------------- */

function reducer(state: GameState, action: GameAction): GameState {
  switch (action.type) {
    case 'SET_PROFILE': {
      return {
        ...state,
        phase: 'story',
        profile: action.profile,
        events: [],
        feedbacks: [],
        player: null,
        worldError: null,
        aiError: null,
        moveError: null,
        timeNarration: '',
      }
    }

    case 'SET_MODE':
      return { ...state, mode: action.mode }

    case 'SET_NARRATION_LANG':
      return { ...state, narrationLang: action.lang }

    // ── 世界加载 ──
    case 'WORLD_LOADING':
      return { ...state, worldLoading: true, worldError: null }

    case 'WORLD_LOADED': {
      const start = action.world.player_start
      const startLoc = action.world.locations.find((l) => l.id === start.location)
      const events = startLoc ? buildEnterEvents(startLoc, '', true) : []
      return {
        ...state,
        worldLoading: false,
        worldError: null,
        world: action.world,
        player: { ...start, visit_counts: { [start.location]: 1 } },
        events,
        aiLoading: true, // 等待 AI 生成开场
      }
    }

    case 'WORLD_ERROR':
      return { ...state, worldLoading: false, worldError: action.error }

    // ── 移动 ──
    case 'MOVE_START':
      return { ...state, moving: true, moveError: null, awaitingInput: false }

    case 'MOVE_SUCCESS': {
      const r = action.result
      if (!r.ok || !r.player_state || !r.location) {
        return { ...state, moving: false, moveError: r.reason || '移动失败' }
      }
      const loc = r.location
      const visits = r.player_state.visit_counts[action.target] ?? 1
      const isFirstVisit = visits <= 1

      // r.location 来自后端，字段与 WorldLocation 不完全一致（缺 variants/state_fields），
      // 这里只取 buildEnterEvents 需要的字段构造一个最小对象
      const enterLoc: WorldLocation = {
        id: loc.id,
        name: loc.name,
        name_en: loc.name_en,
        open_hours: [0, 24],
        travel_cost: loc.travel_cost,
        connections: loc.connections,
        resident_npcs: loc.resident_npcs,
        sensory: loc.sensory,
        variants: {},
        state_fields: {},
      }

      const newEvents = buildEnterEvents(enterLoc, r.time_narration, isFirstVisit)

      return {
        ...state,
        moving: false,
        moveError: null,
        player: r.player_state,
        events: [...state.events, ...newEvents],
        timeNarration: r.time_narration,
        dialogue: { eventId: null, status: 'idle', repeatToken: 0 },
        awaitingInput: false,
        // 第 4 次及以后进入不再调用 AI（成本控制，设计文档 5.5）
        aiLoading: visits < 4,
      }
    }

    case 'MOVE_ERROR':
      return { ...state, moving: false, moveError: action.error }

    // ── 等待 ──
    case 'WAIT_START':
      return { ...state, moving: true, moveError: null }

    case 'WAIT_SUCCESS': {
      const r = action.result
      if (!r.ok || !r.player_state) {
        return { ...state, moving: false, moveError: r.reason || '等待失败' }
      }
      const narrationEvent: GameEvent = {
        id: nextId('ev'),
        kind: 'narration',
        zh: r.time_narration,
        en: '',
      }
      return {
        ...state,
        moving: false,
        player: r.player_state,
        events: [...state.events, narrationEvent],
        timeNarration: r.time_narration,
        awaitingInput: true,
      }
    }

    // ── 对话 ──
    case 'SUBMIT_INPUT': {
      if (state.phase !== 'story' || state.aiLoading) return state
      const playerEvent: GameEvent = {
        id: nextId('ev'),
        kind: 'player_input',
        speech: action.speech,
        action: action.action,
      }
      return {
        ...state,
        events: [...state.events, playerEvent],
        aiLoading: true,
        aiError: null,
        awaitingInput: false,
      }
    }

    case 'AI_TURN_SUCCESS': {
      const result = action.result
      const narrationEvent: GameEvent = {
        id: nextId('ev'),
        kind: 'narration',
        zh: result.narration.zh,
        en: result.narration.en,
      }
      const dialogueEvent: GameEvent = {
        id: nextId('ev'),
        kind: 'npc_dialogue',
        speakerId: result.npc.speaker_id,
        speakerName: result.npc.speaker_name,
        content: result.npc.content,
      }

      const feedback: ExpressionFeedback = result.feedback
        ? {
            id: nextId('fb'),
            userInput: '',
            understood: result.feedback.understood,
            naturalness: result.feedback.naturalness,
            naturalnessNote: result.feedback.naturalness_note,
            appropriateness: result.feedback.appropriateness,
            appropriatenessNote: result.feedback.appropriateness_note,
            suggestedExpression: result.feedback.suggested_expression || '',
            suggestionReason: result.feedback.suggestion_reason || '',
          }
        : {
            id: nextId('fb'),
            userInput: '',
            understood: true,
            naturalness: 'good',
            naturalnessNote: '',
            appropriateness: 'good',
            appropriatenessNote: '',
            suggestedExpression: '',
            suggestionReason: '',
          }

      // 用玩家输入填充反馈
      const lastPlayer = [...state.events].reverse().find((e) => e.kind === 'player_input')
      if (lastPlayer && lastPlayer.kind === 'player_input') {
        feedback.userInput = lastPlayer.speech || lastPlayer.action || ''
      }

      // 世界状态变更由代码校验后应用
      let player = state.player
      if (player && result.world_changes) {
        player = applyWorldChanges(player, result.world_changes, state.world)
      }

      return {
        ...state,
        events: [...state.events, narrationEvent, dialogueEvent],
        feedbacks: [...state.feedbacks, feedback],
        player,
        dialogue: { eventId: dialogueEvent.id, status: 'speaking', repeatToken: 0 },
        awaitingInput: false,
        aiLoading: false,
        aiError: null,
      }
    }

    case 'AI_TURN_ERROR':
      // 世界层下不降级到 mock（mock 数据已废弃），直接报错让用户重试
      return {
        ...state,
        aiLoading: false,
        aiError: `AI 调用失败: ${action.error}`,
        awaitingInput: true,
      }

    case 'AI_OPENING_SUCCESS': {
      const result = action.result
      const narrationEvent: GameEvent = {
        id: nextId('ev'),
        kind: 'narration',
        zh: result.narration.zh,
        en: result.narration.en,
      }
      const dialogueEvent: GameEvent = {
        id: nextId('ev'),
        kind: 'npc_dialogue',
        speakerId: result.npc.speaker_id,
        speakerName: result.npc.speaker_name,
        content: result.npc.content,
      }
      return {
        ...state,
        events: [...state.events, narrationEvent, dialogueEvent],
        dialogue: { eventId: dialogueEvent.id, status: 'speaking', repeatToken: 0 },
        aiLoading: false,
        aiError: null,
      }
    }

    case 'AI_OPENING_ERROR':
      // 开场失败不阻断——感官细节已由前端渲染
      return {
        ...state,
        aiLoading: false,
        aiError: `AI 开场生成失败: ${action.error}`,
        awaitingInput: true,
      }

    case 'CLEAR_ERROR':
      return { ...state, aiError: null, moveError: null, worldError: null }

    case 'DIALOGUE_DONE':
      return {
        ...state,
        dialogue: { ...state.dialogue, status: 'done' },
        awaitingInput: !state.aiLoading,
      }

    case 'INTERRUPT': {
      if (state.dialogue.status !== 'speaking' && state.dialogue.status !== 'paused')
        return state
      return {
        ...state,
        dialogue: { ...state.dialogue, status: 'interrupted' },
        awaitingInput: true,
      }
    }

    case 'PAUSE':
      if (state.dialogue.status !== 'speaking') return state
      return { ...state, dialogue: { ...state.dialogue, status: 'paused' } }

    case 'RESUME':
      if (state.dialogue.status !== 'paused') return state
      return { ...state, dialogue: { ...state.dialogue, status: 'speaking' } }

    case 'REQUEST_REPEAT':
      return {
        ...state,
        dialogue: {
          ...state.dialogue,
          status: 'speaking',
          repeatToken: state.dialogue.repeatToken + 1,
        },
      }

    case 'RESET':
      return { ...initialState }

    default:
      return state
  }
}

/* ----------------------------- Context ----------------------------- */

interface GameContextValue {
  state: GameState
  dispatch: Dispatch<GameAction>
  submitInput: (speech: string, action: string) => void
  moveTo: (target: string) => Promise<void>
  waitHere: () => Promise<void>
}

const GameContext = createContext<GameContextValue | null>(null)

export function GameProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)

  // 已请求过 AI 开场的地点集合，防止重复触发
  const openingRequestedRef = useRef<Set<string>>(new Set())
  // 已请求过 AI 回合的事件 id
  const turnRequestedRef = useRef<Set<string>>(new Set())

  const submitInput = useCallback((speech: string, action: string) => {
    dispatch({ type: 'SUBMIT_INPUT', speech, action })
  }, [])

  const moveTo = useCallback(
    async (target: string) => {
      if (!state.player) return
      dispatch({ type: 'MOVE_START', target })
      try {
        const result = await fetchMove(state.player, target)
        dispatch({ type: 'MOVE_SUCCESS', result, target })
      } catch (e) {
        dispatch({ type: 'MOVE_ERROR', error: (e as Error).message })
      }
    },
    [state.player],
  )

  const waitHere = useCallback(async () => {
    if (!state.player) return
    dispatch({ type: 'WAIT_START' })
    try {
      const result = await fetchWait(state.player)
      dispatch({ type: 'WAIT_SUCCESS', result })
    } catch (e) {
      dispatch({ type: 'MOVE_ERROR', error: (e as Error).message })
    }
  }, [state.player])

  // ── Effect：进入故事后加载世界 ──
  useEffect(() => {
    if (state.phase !== 'story' || state.world || state.worldLoading) return
    dispatch({ type: 'WORLD_LOADING' })
    fetchWorld()
      .then((w) => dispatch({ type: 'WORLD_LOADED', world: w }))
      .catch((e) => dispatch({ type: 'WORLD_ERROR', error: (e as Error).message }))
  }, [state.phase, state.world, state.worldLoading])

  // ── Effect：AI 开场 ──
  useEffect(() => {
    if (!state.aiLoading || !state.world || !state.player || !state.profile) return

    const locationId = state.player.location
    if (openingRequestedRef.current.has(locationId)) return
    openingRequestedRef.current.add(locationId)

    const loc = state.world.locations.find((l) => l.id === locationId)
    if (!loc) return

    const npc = state.world.npcs.find((n) => n.id === loc.resident_npcs[0])

    let cancelled = false
    fetchOpening(
      loc,
      npc,
      state.profile,
      state.player,
      state.world,
      buildRecentSummary(state.events),
    )
      .then((result) => {
        if (!cancelled) dispatch({ type: 'AI_OPENING_SUCCESS', result, locationId })
      })
      .catch((err) => {
        if (!cancelled) dispatch({ type: 'AI_OPENING_ERROR', error: (err as Error).message })
      })

    return () => {
      cancelled = true
    }
  }, [state.aiLoading, state.player, state.world, state.profile, state.events])

  // ── Effect：AI 回合 ──
  useEffect(() => {
    if (!state.aiLoading || !state.world || !state.player || !state.profile) return

    const last = state.events[state.events.length - 1]
    if (!last || last.kind !== 'player_input') return
    if (turnRequestedRef.current.has(last.id)) return
    turnRequestedRef.current.add(last.id)

    const player = state.player
    const loc = state.world.locations.find((l) => l.id === player.location)
    if (!loc) return
    const npc = state.world.npcs.find((n) => n.id === loc.resident_npcs[0])

    let cancelled = false
    fetchTurn(loc, npc, state.profile, player, state.world, state.events, {
      speech: last.speech,
      action: last.action,
    })
      .then((result) => {
        if (!cancelled) dispatch({ type: 'AI_TURN_SUCCESS', result })
      })
      .catch((err) => {
        if (!cancelled) dispatch({ type: 'AI_TURN_ERROR', error: (err as Error).message })
      })

    return () => {
      cancelled = true
    }
  }, [state.aiLoading, state.events, state.player, state.world, state.profile])

  // 重置时清空记录
  useEffect(() => {
    if (state.phase === 'setup') {
      openingRequestedRef.current.clear()
      turnRequestedRef.current.clear()
    }
  }, [state.phase])

  return (
    <GameContext.Provider value={{ state, dispatch, submitInput, moveTo, waitHere }}>
      {children}
    </GameContext.Provider>
  )
}

/** 从事件流生成最近上下文摘要 */
function buildRecentSummary(events: GameEvent[]): string {
  const recent = events.slice(-6)
  return recent
    .map((e) => {
      switch (e.kind) {
        case 'npc_dialogue':
          return `${e.speakerName}: ${e.content}`
        case 'player_input':
          return `玩家: ${e.speech || e.action || ''}`
        case 'narration':
          return e.zh || e.en
        case 'scene_intro':
          return `[到达 ${e.title}]`
        default:
          return ''
      }
    })
    .filter(Boolean)
    .join('\n')
}

export function useGame(): GameContextValue {
  const ctx = useContext(GameContext)
  if (!ctx) throw new Error('useGame must be used within GameProvider')
  return ctx
}
