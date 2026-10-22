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
import { fetchWorld, fetchMove, fetchWait, fetchJudge } from '../api/world'
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
  JudgeResult,
  MainlineProgress,
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

  // ── 主线 ──
  // 判定结果由后端 mainline.py 计算并随响应返回。
  // 前端不自己算「什么算能办」——规则只能有一份实现。
  mainlineLines: string[]
  progress: MainlineProgress | null

  /**
   * 待裁决的世界变更。
   *
   * AI 返回的 world_changes 不能直接应用，先存在这里，
   * 由 effect 送去 /api/judge，结果回来后再落状态。
   * 放在 reducer 外面是因为判定是异步的（一次 HTTP 往返）。
   */
  pendingChanges: Record<string, unknown> | null
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
  dialogue: { eventId: null, status: 'idle', repeatToken: 0, queue: [] },
  awaitingInput: false,
  moving: false,
  moveError: null,
  aiLoading: false,
  aiError: null,
  timeNarration: '',
  mainlineLines: [],
  progress: null,
  pendingChanges: null,
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
  | { type: 'JUDGE_SUCCESS'; result: JudgeResult }
  | { type: 'JUDGE_FAILED' }
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

/**
 * 把 AI 返回的多句台词展开成事件。
 *
 * 返回 `{ first, rest }`：first 立刻进事件流并用打字机播放，
 * rest 进 dialogue.queue 排队，等前一句打完再逐句追加。
 *
 * 为什么要排队而不是全部追加：三句话同时出现等于给玩家看一段剧本，
 * 玩家还没读到第二句，第一句就已经"说完了"。逐句播才像对话。
 *
 * 兼容旧后端：没有 `lines` 字段时退回 `npc` 单句。
 */
function buildDialogueEvents(result: {
  lines?: { speaker_id: string; speaker_name: string; content: string }[]
  npc: { speaker_id: string; speaker_name: string; content: string }
}): {
  first: Extract<GameEvent, { kind: 'npc_dialogue' }>
  rest: Extract<GameEvent, { kind: 'npc_dialogue' }>[]
} {
  const raw =
    result.lines && result.lines.length > 0 ? result.lines : [result.npc]

  const events = raw
    .filter((l) => (l.content ?? '').trim() !== '')
    .map<Extract<GameEvent, { kind: 'npc_dialogue' }>>((l) => ({
      id: nextId('ev'),
      kind: 'npc_dialogue',
      speakerId: l.speaker_id,
      speakerName: l.speaker_name,
      content: l.content,
    }))

  // AI 一句都没给（极少见）：补一句占位，避免对话气泡完全消失
  if (events.length === 0) {
    events.push({
      id: nextId('ev'),
      kind: 'npc_dialogue',
      speakerId: result.npc?.speaker_id ?? 'unknown',
      speakerName: result.npc?.speaker_name ?? '???',
      content: result.npc?.content ?? '...',
    })
  }

  return { first: events[0], rest: events.slice(1) }
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
        // 起始时刻的主线判定结果，后端已算好
        mainlineLines: action.world.mainline_lines ?? [],
        progress: action.world.progress ?? null,
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

      // 越过截止时间时，让世界自己说出来。
      // 不做成弹窗或红字警告——设计文档 5.4 明确要求压力由世界施加。
      if (r.mainline_just_missed) {
        newEvents.push({
          id: nextId('ev'),
          kind: 'narration',
          zh: '（注册处的公告栏上贴出了一张新的通知，日期是今天。）',
          en: '',
        })
      }

      return {
        ...state,
        moving: false,
        moveError: null,
        player: r.player_state,
        events: [...state.events, ...newEvents],
        timeNarration: r.time_narration,
        mainlineLines: r.mainline_lines ?? state.mainlineLines,
        progress: r.progress ?? state.progress,
        dialogue: { eventId: null, status: 'idle', repeatToken: 0, queue: [] },
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
        mainlineLines: r.mainline_lines ?? state.mainlineLines,
        progress: r.progress ?? state.progress,
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
      // 多句台词：第一句立刻播，其余排队等前一句打完
      const { first: dialogueEvent, rest: queuedDialogue } =
        buildDialogueEvents(result)

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

      // 世界状态变更不在这里应用。
      //
      // AI 的 world_changes 只是提议，真正的判定（地点对不对、材料带没带、
      // 前置步骤做没做）在后端 mainline.py 里。effect 收到 AI 响应后
      // 会把提议交给 /api/judge，结果经 JUDGE_SUCCESS 落回状态。
      // 早期实现在这里直接写 facts，等于让 AI 自己给自己发证。
      return {
        ...state,
        events: [...state.events, narrationEvent, dialogueEvent],
        feedbacks: [...state.feedbacks, feedback],
        dialogue: {
          eventId: dialogueEvent.id,
          status: 'speaking',
          repeatToken: 0,
          queue: queuedDialogue,
        },
        awaitingInput: false,
        aiLoading: false,
        aiError: null,
        // 标记有提议待裁决，effect 据此调用判定器
        pendingChanges: result.world_changes ?? null,
      }
    }

    case 'JUDGE_SUCCESS': {
      const r = action.result
      const newEvents: GameEvent[] = [...state.events]

      // 判定器给出的提示写成旁白，让「办好了」这件事发生在世界里，
      // 而不是弹一个 UI 通知。设计文档 5.4：世界施加压力，UI 不施加。
      if (r.notice) {
        newEvents.push({ id: nextId('ev'), kind: 'narration', zh: r.notice, en: '' })
      }

      return {
        ...state,
        player: r.player_state,
        events: newEvents,
        mainlineLines: r.mainline_lines ?? state.mainlineLines,
        progress: r.progress ?? state.progress,
        pendingChanges: null,
      }
    }

    case 'JUDGE_FAILED':
      // 清掉待裁决标记。若不清理，effect 会因为 pendingChanges
      // 仍是同一个对象而反复重试，变成对后端的无限轮询。
      // 世界这一回合不变化——宁可不动，也不应用未经校验的变更。
      return { ...state, pendingChanges: null }

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
      const { first: dialogueEvent, rest: queuedDialogue } =
        buildDialogueEvents(result)
      return {
        ...state,
        events: [...state.events, narrationEvent, dialogueEvent],
        dialogue: {
          eventId: dialogueEvent.id,
          status: 'speaking',
          repeatToken: 0,
          queue: queuedDialogue,
        },
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

    case 'DIALOGUE_DONE': {
      // 队列里还有台词：播下一句，仍然不放开输入
      if (state.dialogue.queue.length > 0) {
        const [next, ...remaining] = state.dialogue.queue
        return {
          ...state,
          events: [...state.events, next],
          dialogue: {
            eventId: next.id,
            status: 'speaking',
            repeatToken: 0,
            queue: remaining,
          },
          awaitingInput: false,
        }
      }
      // 全部说完，才让玩家输入
      return {
        ...state,
        dialogue: { ...state.dialogue, status: 'done' },
        awaitingInput: !state.aiLoading,
      }
    }

    case 'INTERRUPT': {
      if (state.dialogue.status !== 'speaking' && state.dialogue.status !== 'paused')
        return state
      // 打断 = 玩家插话了，剩下的句子不再说出口。
      // 队列直接丢弃：AI 已按完整台词算过 world_changes，
      // 但玩家不该看到自己打断掉的话。
      return {
        ...state,
        dialogue: { ...state.dialogue, status: 'interrupted', queue: [] },
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
  waitHere: (slots?: number) => Promise<void>
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

  const waitHere = useCallback(
    async (slots = 1) => {
      if (!state.player) return
      dispatch({ type: 'WAIT_START' })
      try {
        const result = await fetchWait(state.player, slots)
        dispatch({ type: 'WAIT_SUCCESS', result })
      } catch (e) {
        dispatch({ type: 'MOVE_ERROR', error: (e as Error).message })
      }
    },
    [state.player],
  )

  // ── Effect：进入故事后加载世界 ──
  useEffect(() => {
    if (state.phase !== 'story' || state.world || state.worldLoading) return
    dispatch({ type: 'WORLD_LOADING' })
    fetchWorld()
      .then((w) => dispatch({ type: 'WORLD_LOADED', world: w }))
      .catch((e) => dispatch({ type: 'WORLD_ERROR', error: (e as Error).message }))
  }, [state.phase, state.world, state.worldLoading])

  // ── Effect：把 AI 提议的变更交给判定器 ──
  //
  // AI 说「她已经给你办好了」只是提议。真正决定事实是否成立的是后端：
  // 人在不在那个地点、材料带没带、前置步骤做没做、窗口过没过。
  // 判定是异步的（一次 HTTP 往返），所以不能在 reducer 里做。
  useEffect(() => {
    if (!state.pendingChanges || !state.player) return

    const changes = state.pendingChanges

    // 空对象 = AI 本回合没有提议任何变更，这是大多数回合的常态。
    // 直接跳过，省一次往返；否则每轮都要为「什么都没发生」多请求一次。
    if (Object.keys(changes).length === 0) {
      dispatch({ type: 'JUDGE_FAILED' })
      return
    }

    let cancelled = false

    fetchJudge(state.player, changes)
      .then((result) => {
        if (cancelled) return
        // 拒绝的变更记到控制台。玩家看不到这些——他看到的只有
        // 办事员说的那句话；世界没有改变这件事本身就是反馈。
        if (result.rejected.length > 0) {
          console.info('[judge] 拒绝的变更', result.rejected)
        }
        dispatch({ type: 'JUDGE_SUCCESS', result })
      })
      .catch((err) => {
        // 判定失败不能让玩家卡住：保留原状态，清掉待裁决标记。
        // 宁可这一回合世界没变化，也不要应用未经校验的变更。
        console.warn('[judge] 判定失败', err)
        if (!cancelled) dispatch({ type: 'JUDGE_FAILED' })
      })

    return () => {
      cancelled = true
    }
  }, [state.pendingChanges, state.player])

  // ── Effect：AI 开场 ──
  useEffect(() => {
    if (!state.aiLoading || !state.world || !state.player || !state.profile) return

    const locationId = state.player.location
    if (openingRequestedRef.current.has(locationId)) return
    openingRequestedRef.current.add(locationId)

    const loc = state.world.locations.find((l) => l.id === locationId)
    if (!loc) return

    let cancelled = false
    // 传入全部 NPC：开场也要知道同行者一起进来了
    fetchOpening(
      loc,
      state.world.npcs,
      state.profile,
      state.player,
      state.world,
      buildRecentSummary(state.events),
      state.mainlineLines,
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

    let cancelled = false
    // 传入全部 NPC：在场者由 buildPresentNPCs 依据「常驻 + 同行」组装
    fetchTurn(
      loc,
      state.world.npcs,
      state.profile,
      player,
      state.world,
      state.events,
      { speech: last.speech, action: last.action },
      state.mainlineLines,
    )
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
