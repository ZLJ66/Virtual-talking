// Mock 故事数据与推演引擎
// 阶段1：用预设剧情脚本 + 关键词反馈模拟 AI 剧情引擎与英语评估引擎
// 这样无需真实大模型即可跑通全部交互，后续阶段2 替换为真实 AI 调用

import type {
  CharacterProfile,
  ExpressionFeedback,
  MockTurnResult,
  SceneDef,
  StoryDef,
} from '../types'

/* ----------------------------- 唯一 id 生成 ----------------------------- */

let idCounter = 0
function nextId(prefix: string): string {
  idCounter += 1
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`
}

/* ----------------------------- 故事：在英国生活的第一天 ----------------------------- */

export const story: StoryDef = {
  id: 'uk_first_day',
  title: '在英国生活的第一天',
  scenes: [
    {
      id: 'convenience_store',
      title: '便利店',
      description:
        '你刚抵达英国，拖着行李走进街角一家便利店，想买点东西垫垫肚子。',
      npcId: 'cashier',
      npcName: 'Cashier',
      openingNarration: {
        zh: '你从货架上拿了一份三明治和一瓶水，走到收银台前。收银员扫码后报了价格。',
        en: 'You grab a sandwich and a bottle of water from the shelf and head to the counter. The cashier scans them and tells you the price.',
      },
      openingDialogue: "That'll be £6.50, please.",
      goal: '付完钱并取回找零',
      nodes: [
        {
          narration: {
            zh: '你递过去一张十英镑的钞票，拿了东西正准备离开。收银员看着你，手里拿着几枚硬币，似乎还想告诉你一件事。',
            en: 'You hand over a ten-pound note and turn to leave with your things. The cashier watches you, holding a few coins, clearly wanting to say something.',
          },
          npc: {
            speakerId: 'cashier',
            speakerName: 'Cashier',
            content:
              "Sorry, I think you might have left before I gave you your change.",
          },
        },
        {
          narration: {
            zh: '收银员笑了笑，把找零递给你。',
            en: 'The cashier smiles and hands you the change.',
          },
          npc: {
            speakerId: 'cashier',
            speakerName: 'Cashier',
            content: 'Of course! Here you go. Have a lovely day!',
          },
          completesScene: true,
          worldChanges: {
            addItem: '找零 £3.50',
            setQuest: { id: 'collect_change', status: 'completed' },
          },
        },
      ],
    },
    {
      id: 'bus_stop',
      title: '公交站',
      description: '离开便利店，你来到街角的公交站，准备搭车去学校报到。',
      npcId: 'stranger',
      npcName: 'A passenger',
      openingNarration: {
        zh: '站牌上写满了线路编号，你看不太明白。旁边一位等车的女士注意到你有些茫然。',
        en: 'The bus stop sign is covered in route numbers and you can\'t quite make sense of it. A woman waiting nearby notices you looking lost.',
      },
      openingDialogue: 'Are you alright, love? You look a bit lost.',
      goal: '打听到去学校的公交车',
      nodes: [
        {
          narration: {
            zh: '她转过身来，指了指站牌上的路线图。',
            en: 'She turns to you and points at the route map on the sign.',
          },
          npc: {
            speakerId: 'stranger',
            speakerName: 'A passenger',
            content:
              'The number 38 goes straight to the university. It should be here in about five minutes.',
          },
        },
        {
          narration: {
            zh: '她提醒你上车时刷卡付费。',
            en: 'She reminds you to tap your card when you get on.',
          },
          npc: {
            speakerId: 'stranger',
            speakerName: 'A passenger',
            content:
              'That\'s right. Just tap your card when you board. It\'s £1.80.',
          },
          completesScene: true,
          worldChanges: {
            setQuest: { id: 'find_bus', status: 'completed' },
          },
        },
      ],
    },
    {
      id: 'cafe',
      title: '咖啡馆',
      description: '到了学校附近，一阵咖啡香气飘来，你走进一家小咖啡馆，想先歇歇脚。',
      npcId: 'barista',
      npcName: 'Barista',
      openingNarration: {
        zh: '咖啡馆里很安静，吧台后的咖啡师抬起头，笑着跟你打招呼。',
        en: 'The café is quiet. The barista behind the counter looks up and greets you with a smile.',
      },
      openingDialogue: 'Hi there! What can I get for you?',
      goal: '点一杯咖啡',
      nodes: [
        {
          narration: {
            zh: '咖啡师等你说明想要哪一种、多大杯。',
            en: 'The barista waits for you to say which kind and what size you\'d like.',
          },
          npc: {
            speakerId: 'barista',
            speakerName: 'Barista',
            content:
              'Sure! What size would you like, and is that to stay or to go?',
          },
        },
        {
          narration: {
            zh: '咖啡师在杯子上做了个记号。',
            en: 'The barista marks the cup.',
          },
          npc: {
            speakerId: 'barista',
            speakerName: 'Barista',
            content: 'Great, that\'ll be £3.20. Anything else?',
          },
        },
        {
          narration: {
            zh: '咖啡师转身开始准备，很快把咖啡递给你。',
            en: 'The barista turns to make your drink and soon hands it over.',
          },
          npc: {
            speakerId: 'barista',
            speakerName: 'Barista',
            content: 'Coming right up! Here you go. Enjoy your first day!',
          },
          completesScene: true,
          worldChanges: {
            addItem: '一杯咖啡',
            setQuest: { id: 'order_coffee', status: 'completed' },
          },
        },
      ],
    },
  ],
}

/* ----------------------------- Mock 推演 ----------------------------- */

/**
 * 根据当前场景、已进行的输入轮数与用户输入，返回本回合的旁白、NPC 台词、反馈。
 * stepIndex 从 0 开始：用户第一次输入 → nodes[0]。
 */
export function mockGenerateTurn(
  scene: SceneDef,
  stepIndex: number,
  speech: string,
  action: string,
  profile: CharacterProfile,
): MockTurnResult {
  const nodes = scene.nodes
  const idx = Math.min(stepIndex, nodes.length - 1)
  const node = nodes[idx]
  const completesScene = Boolean(node.completesScene) || idx >= nodes.length - 1

  const feedback = generateFeedback(speech, action, scene, idx, profile)

  return {
    narration: node.narration,
    npc: node.npc,
    feedback,
    completesScene,
    worldChanges: node.worldChanges,
  }
}

/* ----------------------------- 英语评估（Mock） ----------------------------- */

function generateFeedback(
  speech: string,
  action: string,
  scene: SceneDef,
  stepIndex: number,
  profile: CharacterProfile,
): ExpressionFeedback {
  const input = speech.trim()
  const hasAction = action.trim().length > 0
  const id = nextId('fb')

  // 根据英语水平调整反馈基调：初学者更鼓励，高级更注重细节
  const tone =
    profile.englishLevel === 'beginner'
      ? '别担心，慢慢来——'
      : profile.englishLevel === 'advanced'
        ? '细节上可以更贴近母语者——'
        : ''

  // 1) 空输入：NPC 无法理解意图
  if (!input) {
    return {
      id,
      userInput: '',
      understood: false,
      naturalness: 'needs_improvement',
      naturalnessNote: hasAction
        ? `${tone}你描述了动作，但没说话，NPC 只能看到你的肢体语言。试着用一句话把意图说出来。`
        : `${tone}没有输入英文。NPC 不知道你想表达什么，试着用一句话说明你的意图。`,
      appropriateness: 'ok',
      appropriatenessNote: '',
    }
  }

  // 2) 误把中文填进英文输入框
  const looksLikeChinese = /[\u4e00-\u9fa5]/.test(input)
  if (looksLikeChinese) {
    return {
      id,
      userInput: input,
      understood: false,
      naturalness: 'needs_improvement',
      naturalnessNote:
        '这里是对话输入框，需要用英文表达。你可以先把要说的中文写在动作框里，再用英文把意思说出来。',
      appropriateness: 'ok',
      appropriatenessNote: '',
    }
  }

  const lower = input.toLowerCase()
  const hasPlease = /\bplease\b/.test(lower) || /\bcould\b/.test(lower) || /\bmay\b/.test(lower)
  const isDirectCommand =
    /^(give me|give|tell me|bring me|i want)/.test(lower) && !hasPlease

  // 场景与步进相关的参考表达
  const ref = referenceExpression(scene.id, stepIndex)

  // 3) 过于直接的祈使句：能理解，但语气不够得体
  if (isDirectCommand) {
    return {
      id,
      userInput: input,
      understood: true,
      naturalness: 'needs_improvement',
      naturalnessNote:
        `${tone}意思能听懂，但祈使句（Give me…/I want…）在商店或服务场景里显得太直接，当地人更常用委婉的请求句式。`,
      appropriateness: 'needs_improvement',
      appropriatenessNote: '祈使句在服务场景中显得不太礼貌，建议改用请求句式。',
      suggestedExpression: ref,
      suggestionReason: '用 Could I…/Could I have…, please? 更礼貌自然，也更符合英语交流习惯。',
    }
  }

  // 4) 表达偏短且关键场景缺礼貌词
  if (input.length < 12 && !hasPlease && scene.id === 'convenience_store') {
    return {
      id,
      userInput: input,
      understood: true,
      naturalness: 'ok',
      naturalnessNote: `${tone}意思清楚，但稍显简短。加一个 please 会让语气更自然。`,
      appropriateness: 'ok',
      appropriatenessNote: '',
      suggestedExpression: ref,
      suggestionReason: '在请求类表达后补 please，是英语日常交流的基本礼貌。',
    }
  }

  // 5) 表达得体
  return {
    id,
    userInput: input,
    understood: true,
    naturalness: hasPlease ? 'good' : 'ok',
    naturalnessNote: hasPlease
      ? `${tone}表达清晰得体，语气自然，继续这样表达很好。`
      : `${tone}意思表达清楚了。可以试着加入更自然的礼貌用语或更完整的句式。`,
    appropriateness: hasPlease ? 'good' : 'ok',
    appropriatenessNote: '',
    suggestedExpression: hasPlease ? undefined : ref,
    suggestionReason: hasPlease
      ? undefined
      : '下面是一个更贴近当地人习惯的说法，供参考。',
  }
}

/** 各场景各步骤的参考表达 */
function referenceExpression(sceneId: string, stepIndex: number): string {
  if (sceneId === 'convenience_store') {
    if (stepIndex === 0)
      return 'Excuse me, I think you forgot to give me my change.'
    return 'Oh, sorry! Could I have the change, please?'
  }
  if (sceneId === 'bus_stop') {
    if (stepIndex === 0)
      return 'Excuse me, does the number 38 go to the university?'
    return 'Thank you. Do I just tap my card when I get on?'
  }
  if (sceneId === 'cafe') {
    if (stepIndex === 0) return 'Could I have a medium latte to go, please?'
    if (stepIndex === 1) return 'That\'s all, thank you.'
    return 'Thank you very much!'
  }
  return 'Could you say that again, please?'
}

export { nextId }
