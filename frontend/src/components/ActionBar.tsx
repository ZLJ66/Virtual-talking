// 动作按钮栏：打断 / 暂停 / 继续 / 请求重复 / 下一场景 / 重新开始
// 按当前对话状态与剧情进度决定各按钮可用性
// 快捷键：Alt+I 打断 / Alt+P 暂停 / Alt+C 继续 / Alt+R 请求重复
// 用 Alt 组合键，避免在输入框打字时误输入字符

import { useEffect } from 'react'
import { useGame } from '../state/gameContext'

export function ActionBar() {
  const { state, dispatch } = useGame()
  const { dialogue, sceneComplete, storyComplete } = state

  const canInterrupt =
    dialogue.status === 'speaking' || dialogue.status === 'paused'
  const canPause = dialogue.status === 'speaking'
  const canResume = dialogue.status === 'paused'
  const canRepeat = dialogue.status === 'done' || dialogue.status === 'interrupted'
  const canAdvance = sceneComplete && !storyComplete
  const canRestart = storyComplete

  // 全局键盘快捷键：仅在按钮可用时触发
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // 仅响应 Alt 组合，忽略 Ctrl/Meta 组合（避免与其他快捷键冲突）
      if (!e.altKey || e.ctrlKey || e.metaKey) return
      const k = e.key.toLowerCase()
      if (k === 'i' && canInterrupt) {
        e.preventDefault()
        dispatch({ type: 'INTERRUPT' })
      } else if (k === 'p' && canPause) {
        e.preventDefault()
        dispatch({ type: 'PAUSE' })
      } else if (k === 'c' && canResume) {
        e.preventDefault()
        dispatch({ type: 'RESUME' })
      } else if (k === 'r' && canRepeat) {
        e.preventDefault()
        dispatch({ type: 'REQUEST_REPEAT' })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [canInterrupt, canPause, canResume, canRepeat, dispatch])

  // 优先级：下一场景 / 重新开始（剧情节点变化时显示）
  if (canAdvance || canRestart) {
    return (
      <div className="action-bar">
        {canAdvance && (
          <button
            type="button"
            className="action-btn primary"
            onClick={() => dispatch({ type: 'ADVANCE_SCENE' })}
          >
            前往下一场景 →
          </button>
        )}
        {canRestart && (
          <button
            type="button"
            className="action-btn primary"
            onClick={() => dispatch({ type: 'RESET' })}
          >
            重新开始
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="action-bar">
      <button
        type="button"
        className="action-btn"
        onClick={() => dispatch({ type: 'INTERRUPT' })}
        disabled={!canInterrupt}
        title="立即停止当前展示并插话（Alt+I）"
      >
        ✋ 打断 <kbd>Alt+I</kbd>
      </button>
      <button
        type="button"
        className="action-btn"
        onClick={() => dispatch({ type: 'PAUSE' })}
        disabled={!canPause}
        title="暂停阅读，不改变剧情（Alt+P）"
      >
        ⏸ 暂停 <kbd>Alt+P</kbd>
      </button>
      <button
        type="button"
        className="action-btn"
        onClick={() => dispatch({ type: 'RESUME' })}
        disabled={!canResume}
        title="继续展示（Alt+C）"
      >
        ▶ 继续 <kbd>Alt+C</kbd>
      </button>
      <button
        type="button"
        className="action-btn"
        onClick={() => dispatch({ type: 'REQUEST_REPEAT' })}
        disabled={!canRepeat}
        title="让 NPC 重新说一遍（Alt+R）"
      >
        🔁 请求重复 <kbd>Alt+R</kbd>
      </button>
    </div>
  )
}
