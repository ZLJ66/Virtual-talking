// 英语反馈面板：按练习模式控制显示时机与强度
// 沉浸模式：默认折叠，手动展开查看，不打断对话
// 学习模式：每轮后自动展开最新反馈
// 挑战模式：折叠并提示结束后统一复盘
// 三维度评估：有效性 / 自然度 / 得体度

import { useEffect, useState } from 'react'
import { useGame } from '../state/gameContext'
import type { Naturalness } from '../types'

const NATURALNESS_META: Record<Naturalness, { label: string; cls: string }> = {
  good: { label: '良好', cls: 'nat-good' },
  ok: { label: '一般', cls: 'nat-ok' },
  needs_improvement: { label: '待提升', cls: 'nat-bad' },
}

export function FeedbackPanel() {
  const { state } = useGame()
  const [open, setOpen] = useState(false)

  const latest = state.feedbacks[state.feedbacks.length - 1]

  // 学习模式：有新反馈时自动展开
  useEffect(() => {
    if (state.mode === 'learning' && latest) setOpen(true)
  }, [state.mode, latest?.id])

  if (state.feedbacks.length === 0) return null

  const total = state.feedbacks.length
  const understood = state.feedbacks.filter((f) => f.understood).length
  const natGood = state.feedbacks.filter((f) => f.naturalness === 'good').length

  return (
    <div className="feedback-panel">
      <button
        type="button"
        className="feedback-toggle"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="feedback-title">
          📝 表达反馈
          {state.mode === 'challenge' && '（挑战模式：结束后复盘）'}
        </span>
        <span className="feedback-stats">
          {understood}/{total} 被理解 · {natGood} 自然
        </span>
        <span className="feedback-arrow">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="feedback-list">
          {state.mode === 'challenge' && state.phase !== 'ended' && (
            <p className="challenge-hint">
              挑战模式中暂不显示逐条反馈，故事结束后可统一查看下方已记录的内容。
            </p>
          )}
          {[...state.feedbacks].reverse().map((f, i) => {
            const natMeta = NATURALNESS_META[f.naturalness]
            const appMeta = NATURALNESS_META[f.appropriateness]
            return (
              <div className="feedback-item" key={f.id}>
                <div className="feedback-input">
                  <span className="feedback-num">#{total - i}</span>
                  <code className="feedback-user-input">
                    {f.userInput || '（未输入英文）'}
                  </code>
                </div>
                <div className="feedback-tags">
                  <span className={`tag ${f.understood ? 'tag-good' : 'tag-bad'}`}>
                    {f.understood ? '✓ 已被理解' : '✗ 未被理解'}
                  </span>
                  <span className={`tag ${natMeta.cls}`}>自然度：{natMeta.label}</span>
                  <span className={`tag ${appMeta.cls}`}>得体度：{appMeta.label}</span>
                </div>
                {(f.naturalnessNote || f.appropriatenessNote) && (
                  <p className="feedback-note">
                    {f.naturalnessNote}
                    {f.naturalnessNote && f.appropriatenessNote ? ' ' : ''}
                    {f.appropriatenessNote}
                  </p>
                )}
                {f.suggestedExpression && (
                  <div className="feedback-suggestion">
                    <span className="suggestion-label">更自然的说法：</span>
                    <code>{f.suggestedExpression}</code>
                  </div>
                )}
                {f.suggestionReason && (
                  <p className="feedback-reason">{f.suggestionReason}</p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
