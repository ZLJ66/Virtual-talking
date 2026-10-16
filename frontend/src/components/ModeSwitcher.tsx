// 练习模式切换：沉浸 / 学习 / 挑战
// 三模式共用同一剧情系统，只改变教学反馈的时机与强度

import { useGame } from '../state/gameContext'
import type { PracticeMode } from '../types'

const MODES: { id: PracticeMode; label: string; hint: string }[] = [
  { id: 'immersive', label: '沉浸', hint: '主打体验，不打断对话纠错' },
  { id: 'learning', label: '学习', hint: '每轮后显示表达反馈，可重试' },
  { id: 'challenge', label: '挑战', hint: '尽量不提示，结束后统一复盘' },
]

export function ModeSwitcher() {
  const { state, dispatch } = useGame()
  return (
    <div className="mode-switcher">
      {MODES.map((m) => (
        <button
          key={m.id}
          type="button"
          className={`mode-btn ${state.mode === m.id ? 'active' : ''}`}
          onClick={() => dispatch({ type: 'SET_MODE', mode: m.id })}
          title={m.hint}
        >
          {m.label}
        </button>
      ))}
    </div>
  )
}
