// 核心类型定义
// 注意：项目开启 erasableSyntaxOnly，不能使用 enum，统一用字面量联合类型

/* ----------------------------- 角色与设置 ----------------------------- */

export type EnglishLevel = 'beginner' | 'intermediate' | 'advanced'

export type StoryBackground = 'uk_student' | 'au_immigrant' | 'traveler'

export type NarrationLanguage = 'zh' | 'en' | 'both'

export type PracticeMode = 'immersive' | 'learning' | 'challenge'

export interface CharacterProfile {
  name: string
  gender: string
  englishLevel: EnglishLevel
  storyBackground: StoryBackground
  narrationLanguage: NarrationLanguage
}

/* ----------------------------- 故事事件模型 ----------------------------- */
// 内部保存结构化事件，而非一整段文本。
// 旁白同时保存中英文，切换语言时只需重新呈现，不必重跑剧情。

export type GameEvent =
  | {
      id: string
      kind: 'scene_intro'
      sceneId: string
      title: string
      description: string
    }
  | { id: string; kind: 'narration'; zh: string; en: string }
  | {
      id: string
      kind: 'npc_dialogue'
      speakerId: string
      speakerName: string
      content: string
      sceneId?: string
    }
  | { id: string; kind: 'player_input'; speech: string; action: string }
  | { id: string; kind: 'action_result'; zh: string; en: string }
  | { id: string; kind: 'scene_transition'; to: string; summary: string }

/* ----------------------------- 英语反馈 ----------------------------- */

export type Naturalness = 'good' | 'ok' | 'needs_improvement'

export interface ExpressionFeedback {
  id: string
  userInput: string
  understood: boolean // 表达是否有效：NPC 能否理解意图
  naturalness: Naturalness // 表达是否自然
  naturalnessNote: string
  appropriateness: Naturalness // 得体度：在社交场景中是否恰当
  appropriatenessNote: string
  suggestedExpression?: string
  suggestionReason?: string
}

/* ----------------------------- 世界状态 ----------------------------- */
//
// 阶段 A：旧的 WorldState（storyId/currentScene/questStatus）已被
// types/world.ts 的 PlayerState 取代。进度不再由场景索引表达，
// 而由 location + time + facts + npc_states 表达。
//
// 旧的 StoryNode / SceneDef / StoryDef / MockTurnResult 已随
// data/mockStory.ts 一并删除——线性场景结构不兼容自由移动。

/* ----------------------------- 运行期对话展示状态 ----------------------------- */

export type DialogueStatus = 'idle' | 'speaking' | 'paused' | 'interrupted' | 'done'

export interface DialogueDisplay {
  /** 当前正在展示的对话事件 id */
  eventId: string | null
  status: DialogueStatus
  /** 请求重复的令牌：每次请求重复时自增，组件据此重置打字进度 */
  repeatToken: number
}

/* ----------------------------- 全局游戏状态 ----------------------------- */

export type GamePhase = 'setup' | 'story' | 'ended'
