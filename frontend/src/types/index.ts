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

export interface WorldState {
  storyId: string
  currentScene: string
  currentNpc: string
  inventory: string[]
  questStatus: Record<string, string>
  lastEvent: string
}

/* ----------------------------- 场景与节点（Mock 数据用） ----------------------------- */

export interface StoryNode {
  /** NPC 的旁白 */
  narration: { zh: string; en: string }
  /** NPC 台词 */
  npc: {
    speakerId: string
    speakerName: string
    content: string
  }
  /** 本节点是否完成本场景目标 */
  completesScene?: boolean
  /** 完成本节点后的世界状态变更 */
  worldChanges?: {
    addItem?: string
    setQuest?: { id: string; status: string }
    setNpc?: string
  }
}

export interface SceneDef {
  id: string
  title: string
  /** 场景开场描述（scene_intro 的 description） */
  description: string
  npcId: string
  npcName: string
  /** 场景开场旁白 */
  openingNarration: { zh: string; en: string }
  /** 场景开场 NPC 台词 */
  openingDialogue: string
  /** 按顺序推进的交互节点 */
  nodes: StoryNode[]
  /** 场景目标（用于提示） */
  goal: string
}

export interface StoryDef {
  id: string
  title: string
  scenes: SceneDef[]
}

/* ----------------------------- Mock 推演结果 ----------------------------- */

export interface MockTurnResult {
  /** 本回合生成的旁白 */
  narration: { zh: string; en: string }
  /** 本回合的 NPC 台词 */
  npc: { speakerId: string; speakerName: string; content: string }
  /** 本回合针对用户输入的英语反馈 */
  feedback: ExpressionFeedback
  /** 是否完成当前场景 */
  completesScene: boolean
  /** 世界状态变更 */
  worldChanges?: StoryNode['worldChanges']
}

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
