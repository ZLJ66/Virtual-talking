// 双输入框：话语输入（英文）+ 动作输入（中/英）
// 仅在 awaitingInput 时可用
// AI 加载中禁用输入并显示等待提示

import { useState } from 'react'
import { useGame } from '../state/gameContext'

export function InputBar() {
  const { state, submitInput } = useGame()
  const [speech, setSpeech] = useState('')
  const [action, setAction] = useState('')

  const blocked =
    !state.awaitingInput ||
    state.dialogue.status === 'speaking' ||
    state.aiLoading

  const canSubmit =
    !blocked && (speech.trim().length > 0 || action.trim().length > 0)

  const handleSubmit = () => {
    if (!canSubmit) return
    submitInput(speech.trim(), action.trim())
    setSpeech('')
    setAction('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Ctrl/Cmd + Enter 提交
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className={`input-bar ${blocked ? 'blocked' : ''}`}>
      <div className="input-row">
        <label className="input-label" htmlFor="speech-input">
          话语（英文）
        </label>
        <textarea
          id="speech-input"
          className="speech-input"
          value={speech}
          onChange={(e) => setSpeech(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            state.aiLoading
              ? '🤔 AI 正在构思回复…'
              : blocked
                ? '等待 NPC 说完…'
                : '用英文说出你想表达的话，例如：Excuse me, could I have the change, please?'
          }
          disabled={blocked}
          rows={2}
        />
      </div>
      <div className="input-row">
        <label className="input-label" htmlFor="action-input">
          动作（中文或英文，可选）
        </label>
        <input
          id="action-input"
          className="action-input"
          value={action}
          onChange={(e) => setAction(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            blocked
              ? ''
              : '描述表情、动作或观察，例如：捂着肚子，微微皱眉'
          }
          disabled={blocked}
        />
      </div>
      <button
        type="button"
        className="submit-btn"
        onClick={handleSubmit}
        disabled={!canSubmit}
      >
        {state.aiLoading ? '🤔 思考中…' : '发送（Ctrl+Enter）'}
      </button>
    </div>
  )
}
