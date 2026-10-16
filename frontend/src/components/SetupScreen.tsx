// 角色设置页：配置角色档案后进入故事
// 名字/性别可选，英语水平与故事背景为必选

import { useState } from 'react'
import { useGame } from '../state/gameContext'
import type {
  EnglishLevel,
  NarrationLanguage,
  StoryBackground,
} from '../types'

const ENGLISH_LEVELS: { id: EnglishLevel; label: string; desc: string }[] = [
  { id: 'beginner', label: '初级', desc: '能说简单句子，靠单词拼凑' },
  { id: 'intermediate', label: '中级', desc: '能完成日常对话，但不够地道' },
  { id: 'advanced', label: '高级', desc: '能流利表达，想更自然' },
]

const BACKGROUNDS: { id: StoryBackground; label: string; desc: string }[] = [
  { id: 'uk_student', label: '英国留学生', desc: '刚到英国，开始留学生活' },
  { id: 'au_immigrant', label: '澳洲新移民', desc: '在澳大利亚定居，融入生活' },
  { id: 'traveler', label: '海外旅行者', desc: '短期海外旅行，应对日常场景' },
]

const LANGS: { id: NarrationLanguage; label: string }[] = [
  { id: 'both', label: '中英双语' },
  { id: 'zh', label: '仅中文' },
  { id: 'en', label: '仅英文' },
]

export function SetupScreen() {
  const { dispatch } = useGame()
  const [name, setName] = useState('')
  const [gender, setGender] = useState('')
  const [englishLevel, setEnglishLevel] = useState<EnglishLevel>('intermediate')
  const [storyBackground, setStoryBackground] =
    useState<StoryBackground>('uk_student')
  const [narrationLanguage, setNarrationLanguage] =
    useState<NarrationLanguage>('both')

  const handleStart = () => {
    dispatch({
      type: 'SET_PROFILE',
      profile: {
        name: name.trim() || 'Alex',
        gender: gender.trim(),
        englishLevel,
        storyBackground,
        narrationLanguage,
      },
    })
  }

  return (
    <div className="setup-screen">
      <div className="setup-card">
        <h1 className="setup-title">AI 沉浸式英语表达模拟器</h1>
        <p className="setup-subtitle">
          在连续的剧情中自由组织英文、描述动作，让表达在真实语境中逐渐自然。
        </p>

        <div className="setup-form">
          <div className="form-row two-col">
            <div className="form-field">
              <label htmlFor="name">名字（可选）</label>
              <input
                id="name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Alex"
              />
            </div>
            <div className="form-field">
              <label htmlFor="gender">性别（可选）</label>
              <input
                id="gender"
                type="text"
                value={gender}
                onChange={(e) => setGender(e.target.value)}
                placeholder="留空"
              />
            </div>
          </div>

          <div className="form-field">
            <label>英语水平</label>
            <div className="option-group">
              {ENGLISH_LEVELS.map((lv) => (
                <button
                  key={lv.id}
                  type="button"
                  className={`option-card ${englishLevel === lv.id ? 'selected' : ''}`}
                  onClick={() => setEnglishLevel(lv.id)}
                >
                  <span className="option-label">{lv.label}</span>
                  <span className="option-desc">{lv.desc}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="form-field">
            <label>故事背景</label>
            <div className="option-group">
              {BACKGROUNDS.map((bg) => (
                <button
                  key={bg.id}
                  type="button"
                  className={`option-card ${storyBackground === bg.id ? 'selected' : ''}`}
                  onClick={() => setStoryBackground(bg.id)}
                >
                  <span className="option-label">{bg.label}</span>
                  <span className="option-desc">{bg.desc}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="form-field">
            <label>旁白语言</label>
            <div className="option-group inline">
              {LANGS.map((lg) => (
                <button
                  key={lg.id}
                  type="button"
                  className={`option-pill ${narrationLanguage === lg.id ? 'selected' : ''}`}
                  onClick={() => setNarrationLanguage(lg.id)}
                >
                  {lg.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <button type="button" className="start-btn" onClick={handleStart}>
          开始故事 →
        </button>
      </div>
    </div>
  )
}
