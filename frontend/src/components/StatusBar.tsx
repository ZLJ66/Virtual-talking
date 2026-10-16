// 状态栏：场景进度 / 旁白语言切换 / 世界状态查看 / 模式切换

import { useState } from 'react'
import { useGame } from '../state/gameContext'
import { story } from '../data/mockStory'
import type { NarrationLanguage } from '../types'
import { ModeSwitcher } from './ModeSwitcher'

const LANG_LABELS: Record<NarrationLanguage, string> = {
  both: '中英',
  zh: '中文',
  en: '英文',
}

export function StatusBar() {
  const { state, dispatch } = useGame()
  const [showWorld, setShowWorld] = useState(false)
  const scene = story.scenes[state.sceneIndex]

  return (
    <div className="status-bar">
      <div className="status-left">
        <span className="status-scene">
          场景 {Math.min(state.sceneIndex + 1, story.scenes.length)}/
          {story.scenes.length}：{scene?.title ?? '—'}
        </span>
        {scene && <span className="status-goal">目标：{scene.goal}</span>}
      </div>

      <div className="status-center">
        <ModeSwitcher />
      </div>

      <div className="status-right">
        <div className="lang-switch" role="group" aria-label="旁白语言">
          {(['both', 'zh', 'en'] as NarrationLanguage[]).map((l) => (
            <button
              key={l}
              type="button"
              className={`lang-btn ${state.narrationLang === l ? 'active' : ''}`}
              onClick={() => dispatch({ type: 'SET_NARRATION_LANG', lang: l })}
            >
              {LANG_LABELS[l]}
            </button>
          ))}
        </div>

        <button
          type="button"
          className="ghost-btn"
          onClick={() => setShowWorld((s) => !s)}
        >
          🌍 世界状态
        </button>

        <button
          type="button"
          className="ghost-btn"
          onClick={() => dispatch({ type: 'RESET' })}
        >
          重新开始
        </button>
      </div>

      {showWorld && state.worldState && (
        <div className="world-popover">
          <h4>当前世界状态</h4>
          <dl className="world-grid">
            <dt>当前场景</dt>
            <dd>{state.worldState.currentScene}</dd>
            <dt>当前 NPC</dt>
            <dd>{state.worldState.currentNpc}</dd>
            <dt>物品栏</dt>
            <dd>
              {state.worldState.inventory.length > 0
                ? state.worldState.inventory.join('、')
                : '（空）'}
            </dd>
            <dt>任务进度</dt>
            <dd>
              {Object.keys(state.worldState.questStatus).length > 0
                ? Object.entries(state.worldState.questStatus)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join('；')
                : '（无）'}
            </dd>
          </dl>
        </div>
      )}
    </div>
  )
}
