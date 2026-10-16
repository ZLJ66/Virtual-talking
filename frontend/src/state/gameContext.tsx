// 游戏状态管理：useReducer + Context
// 负责回合推进、打断/暂停/请求重复、场景切换、世界状态与反馈记录
// 阶段2：AI 回合改为异步调用，loading/error 状态由 reducer 管理

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
import { mockGenerateTurn, nextId, story } from '../data/mockStory'
import type {
  CharacterProfile,
  DialogueDisplay,
  ExpressionFeedback,
  GameEvent,
  GamePhase,
  NarrationLanguage,
  PracticeMode,
  WorldState,
} from '../types'

/* ----------------------------- State ----------------------------- */

export interface GameState {
  phase: GamePhase
  profile: CharacterProfile | null
  mode: PracticeMode
  narrationLang: NarrationLanguage
  events: GameEvent[]
  feedbacks: ExpressionFeedback[]
  worldState: WorldState | null
  sceneIndex: number
  stepIndex: number
  dialogue: DialogueDisplay
  awaitingInput: boolean
  sceneComplete: boolean
  storyComplete: boolean
  // 异步 AI 调用状态
  aiLoading: boolean
  aiError: string | null
}

const initialState: GameState = {
  phase: 'setup',
  profile: null,
  mode: 'immersive',
  narrationLang: 'both',
  events: [],
  feedbacks: [],
  worldState: null,
  sceneIndex: 0,
  stepIndex: 0,
  dialogue: { eventId: null, status: 'idle', repeatToken: 0 },
  awaitingInput: false,
  sceneComplete: false,
  storyComplete: false,
  aiLoading: false,
  aiError: null,
}

/* ----------------------------- Actions ----------------------------- */

export type GameAction =
  | { type: 'SET_PROFILE'; profile: CharacterProfile }
  | { type: 'SET_MODE'; mode: PracticeMode }
  | { type: 'SET_NARRATION_LANG'; lang: NarrationLanguage }
  | { type: 'SUBMIT_INPUT'; speech: string; action: string }
  | { type: 'AI_TURN_SUCCESS'; result: AITurnResponse }
  | { type: 'AI_TURN_ERROR'; error: string }
  | { type: 'AI_OPENING_SUCCESS'; result: AIOpeningResponse; sceneIndex: number }
  | { type: 'AI_OPENING_ERROR'; error: string }
  | { type: 'DIALOGUE_DONE' }
  | { type: 'INTERRUPT' }
  | { type: 'PAUSE' }
  | { type: 'RESUME' }
  | { type: 'REQUEST_REPEAT' }
  | { type: 'ADVANCE_SCENE' }
  | { type: 'RESET' }
  | { type: 'CLEAR_ERROR' }

/* ----------------------------- 辅助：进入场景（硬编码开场） ----------------------------- */

function enterSceneHardcoded(state: GameState, sceneIndex: number): Partial<GameState> {
  const scene = story.scenes[sceneIndex]
  const introId = nextId('ev')
  const narrationId = nextId('ev')
  const dialogueId = nextId('ev')

  const newEvents: GameEvent[] = [
    {
      id: introId,
      kind: 'scene_intro',
      sceneId: scene.id,
      title: scene.title,
      description: scene.description,
    },
    { id: narrationId, kind: 'narration', zh: scene.openingNarration.zh, en: scene.openingNarration.en },
    {
      id: dialogueId,
      kind: 'npc_dialogue',
      sceneId: scene.id,
      speakerId: scene.npcId,
      speakerName: scene.npcName,
      content: scene.openingDialogue,
    },
  ]

  const worldState: WorldState = state.worldState
    ? {
        ...state.worldState,
        currentScene: scene.id,
        currentNpc: scene.npcId,
        lastEvent: `scene_${scene.id}_intro`,
      }
    : {
        storyId: story.id,
        currentScene: scene.id,
        currentNpc: scene.npcId,
        inventory: [],
        questStatus: {},
        lastEvent: `scene_${scene.id}_intro`,
      }

  return {
    sceneIndex,
    stepIndex: 0,
    events: [...state.events, ...newEvents],
    worldState,
    dialogue: { eventId: dialogueId, status: 'speaking', repeatToken: 0 },
    awaitingInput: false,
    sceneComplete: false,
  }
}

/* ----------------------------- 辅助：AI 开场覆盖旁白+对话 ----------------------------- */

function applyOpeningResult(
  state: GameState,
  sceneIndex: number,
  result: AIOpeningResponse,
): Partial<GameState> {
  const scene = story.scenes[sceneIndex]
  // 生成新的 NPC 对话事件 id，确保 DialogueBubble 重置打字进度
  const newDialogueId = nextId('ev')
  // 替换 narration 和 npc_dialogue 的内容；npc_dialogue 换新 id
  const events = state.events.map((ev) => {
    if (ev.kind === 'narration') {
      return { ...ev, zh: result.narration.zh, en: result.narration.en }
    }
    if (ev.kind === 'npc_dialogue' && ev.sceneId === scene.id) {
      return {
        ...ev,
        id: newDialogueId,
        speakerId: result.npc.speaker_id || scene.npcId,
        speakerName: result.npc.speaker_name || scene.npcName,
        content: result.npc.content,
      }
    }
    return ev
  })

  return {
    events,
    // 用新 id 重启打字机
    dialogue: { eventId: newDialogueId, status: 'speaking', repeatToken: 0 },
    aiLoading: false,
    aiError: null,
  }
}

/* ----------------------------- 辅助：应用 AI 回合结果 ----------------------------- */

function applyTurnResult(state: GameState, result: AITurnResponse): Partial<GameState> {
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

  // 更新世界状态
  const worldState: WorldState = { ...state.worldState! }
  if (result.world_changes?.add_item) {
    worldState.inventory = [...worldState.inventory, result.world_changes.add_item]
  }
  if (result.world_changes?.set_quest) {
    worldState.questStatus = {
      ...worldState.questStatus,
      [result.world_changes.set_quest.id]: result.world_changes.set_quest.status,
    }
  }
  if (result.world_changes?.set_npc) {
    worldState.currentNpc = result.world_changes.set_npc
  }
  worldState.lastEvent = `turn_${state.sceneIndex}_${state.stepIndex}`

  // 构造反馈
  const feedback: ExpressionFeedback = result.feedback
    ? {
        id: nextId('fb'),
        userInput: '', // 由调用方填入
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

  return {
    events: [...state.events, narrationEvent, dialogueEvent],
    feedbacks: [...state.feedbacks, feedback],
    worldState,
    stepIndex: state.stepIndex + 1,
    dialogue: { eventId: dialogueEvent.id, status: 'speaking', repeatToken: 0 },
    awaitingInput: false,
    sceneComplete: result.completes_scene,
    aiLoading: false,
    aiError: null,
  }
}

/* ----------------------------- Reducer ----------------------------- */

function reducer(state: GameState, action: GameAction): GameState {
  switch (action.type) {
    case 'SET_PROFILE': {
      const base: GameState = {
        ...state,
        phase: 'story',
        profile: action.profile,
        sceneIndex: 0,
        stepIndex: 0,
        events: [],
        feedbacks: [],
        worldState: null,
        storyComplete: false,
        aiLoading: true, // 等待 AI 开场
        aiError: null,
      }
      return { ...base, ...enterSceneHardcoded(base, 0) }
    }

    case 'SET_MODE':
      return { ...state, mode: action.mode }

    case 'SET_NARRATION_LANG':
      return { ...state, narrationLang: action.lang }

    case 'SUBMIT_INPUT': {
      if (state.phase !== 'story' || state.sceneComplete || state.aiLoading) return state

      // 先添加玩家输入事件
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
      // 把反馈关联到玩家输入
      const result = applyTurnResult(state, action.result)
      // 用玩家输入填充最新反馈的 userInput
      const newFeedbacks = [...result.feedbacks!]
      const lastPlayerEvent = [...state.events].reverse().find((e) => e.kind === 'player_input')
      if (newFeedbacks.length > 0 && lastPlayerEvent) {
        newFeedbacks[newFeedbacks.length - 1] = {
          ...newFeedbacks[newFeedbacks.length - 1],
          userInput: lastPlayerEvent.speech || lastPlayerEvent.action || '',
        }
      }
      return { ...state, ...result, feedbacks: newFeedbacks }
    }

    case 'AI_TURN_ERROR': {
      // 降级到 mock
      const scene = story.scenes[state.sceneIndex]
      if (!scene || !state.profile) {
        return { ...state, aiLoading: false, aiError: action.error }
      }
      const lastPlayerEvent = [...state.events].reverse().find((e) => e.kind === 'player_input')
      const speech = lastPlayerEvent?.speech || ''
      const act = lastPlayerEvent?.action || ''

      const mockResult = mockGenerateTurn(scene, state.stepIndex, speech, act, state.profile)
      // 构造 AITurnResponse 格式的 fallback（snake_case 字段）
      const fallback: AITurnResponse = {
        narration: mockResult.narration,
        npc: {
          speaker_id: mockResult.npc.speakerId,
          speaker_name: mockResult.npc.speakerName,
          content: mockResult.npc.content,
        },
        feedback: {
          understood: mockResult.feedback.understood,
          naturalness: mockResult.feedback.naturalness,
          naturalness_note: mockResult.feedback.naturalnessNote,
          appropriateness: mockResult.feedback.appropriateness,
          appropriateness_note: mockResult.feedback.appropriatenessNote,
          suggested_expression: mockResult.feedback.suggestedExpression ?? '',
          suggestion_reason: mockResult.feedback.suggestionReason ?? '',
        },
        completes_scene: mockResult.completesScene,
        world_changes: mockResult.worldChanges
          ? {
              add_item: mockResult.worldChanges.addItem,
              set_quest: mockResult.worldChanges.setQuest,
              set_npc: mockResult.worldChanges.setNpc,
            }
          : {},
      }
      const result = applyTurnResult(state, fallback)
      // 用玩家输入填充反馈的 userInput
      const newFeedbacks = [...result.feedbacks!]
      if (newFeedbacks.length > 0) {
        newFeedbacks[newFeedbacks.length - 1] = {
          ...newFeedbacks[newFeedbacks.length - 1],
          userInput: speech || act,
        }
      }
      return {
        ...state,
        ...result,
        feedbacks: newFeedbacks,
        aiLoading: false,
        aiError: `AI 调用失败，已使用本地回复: ${action.error}`,
      }
    }

    case 'AI_OPENING_SUCCESS':
      return { ...state, ...applyOpeningResult(state, action.sceneIndex, action.result) }

    case 'AI_OPENING_ERROR':
      // 开场失败不需要降级，硬编码开场仍然可用
      return { ...state, aiLoading: false, aiError: `AI 开场生成失败: ${action.error}` }

    case 'CLEAR_ERROR':
      return { ...state, aiError: null }

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

    case 'ADVANCE_SCENE': {
      if (!state.sceneComplete) return state
      if (state.sceneIndex >= story.scenes.length - 1) {
        return { ...state, storyComplete: true, phase: 'ended' }
      }
      const nextSceneIdx = state.sceneIndex + 1
      const entered = enterSceneHardcoded(state, nextSceneIdx)
      return {
        ...state,
        ...entered,
        aiLoading: true, // 等待 AI 生成新场景开场
      }
    }

    case 'RESET':
      return { ...initialState }

    default:
      return state
  }
}

/* ----------------------------- Context + 异步调度 ----------------------------- */

interface GameContextValue {
  state: GameState
  dispatch: Dispatch<GameAction>
  /** 提交输入（触发 AI 回合） */
  submitInput: (speech: string, action: string) => void
}

const GameContext = createContext<GameContextValue | null>(null)

export function GameProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)

  // 用 ref 追踪哪些场景已请求过 AI 开场，防止 StrictMode 双重触发
  const openingRequestedRef = useRef<Set<number>>(new Set())

  // 提交输入：先 dispatch 玩家输入事件，AI 调用在 effect 中处理
  const submitInput = useCallback(
    (speech: string, action: string) => {
      dispatch({ type: 'SUBMIT_INPUT', speech, action })
    },
    [dispatch],
  )

  // ── Effect：AI 回合请求 ──
  // 当 aiLoading=true 且有 player_input 事件需要 AI 回应时，发起 /api/turn
  useEffect(() => {
    if (!state.aiLoading || !state.profile || !state.worldState) return

    const scene = story.scenes[state.sceneIndex]
    if (!scene) return

    // 检查是否需要生成回合（最后一个事件是 player_input，且还没有对应的 AI 回应）
    const lastEvent = state.events[state.events.length - 1]
    if (lastEvent?.kind !== 'player_input') return

    const speech = lastEvent.speech
    const action = lastEvent.action

    let cancelled = false
    fetchTurn(scene, state.profile, state.worldState, state.events, { speech, action })
      .then((result) => {
        if (!cancelled) dispatch({ type: 'AI_TURN_SUCCESS', result })
      })
      .catch((err) => {
        if (!cancelled) dispatch({ type: 'AI_TURN_ERROR', error: (err as Error).message })
      })

    return () => { cancelled = true }
  }, [state.aiLoading, state.sceneIndex, state.profile, state.worldState, state.events])

  // ── Effect：AI 开场请求 ──
  // 当进入新场景且 aiLoading=true 时，发起 /api/opening
  useEffect(() => {
    if (!state.aiLoading || !state.profile || state.phase !== 'story') return
    // 检查是否已请求过此场景的开场
    if (openingRequestedRef.current.has(state.sceneIndex)) return
    openingRequestedRef.current.add(state.sceneIndex)

    const scene = story.scenes[state.sceneIndex]
    if (!scene) return

    const prevSummary = state.sceneIndex > 0
      ? `玩家完成了「${story.scenes[state.sceneIndex - 1].title}」场景`
      : undefined

    let cancelled = false
    fetchOpening(scene, state.profile, prevSummary)
      .then((result) => {
        if (!cancelled) dispatch({ type: 'AI_OPENING_SUCCESS', result, sceneIndex: state.sceneIndex })
      })
      .catch((err) => {
        if (!cancelled) dispatch({ type: 'AI_OPENING_ERROR', error: (err as Error).message })
      })

    return () => { cancelled = true }
  }, [state.aiLoading, state.sceneIndex, state.profile, state.phase])

  // 重置时清空开场请求记录
  useEffect(() => {
    if (state.phase === 'setup') {
      openingRequestedRef.current.clear()
    }
  }, [state.phase])

  return (
    <GameContext.Provider value={{ state, dispatch, submitInput }}>
      {children}
    </GameContext.Provider>
  )
}

export function useGame(): GameContextValue {
  const ctx = useContext(GameContext)
  if (!ctx) throw new Error('useGame must be used within GameProvider')
  return ctx
}
