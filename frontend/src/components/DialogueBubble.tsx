// NPC 对话气泡：带逐字打字机效果
// 关键：只有"当前活跃"的对话用打字机，其余对话静态显示全文
// 打断：只展示打断前已经逐字打出的那一部分，剩余文字不再露出
// 完成：自然打完时显示全文

import { useEffect, useRef, useState } from 'react'
import { useGame } from '../state/gameContext'
import type { GameEvent } from '../types'

interface Props {
  event: Extract<GameEvent, { kind: 'npc_dialogue' }>
}

const TYPE_SPEED_MS = 38

export function DialogueBubble({ event }: Props) {
  const { state, dispatch } = useGame()
  const { status, repeatToken } = state.dialogue
  const [visible, setVisible] = useState(0)
  const doneRef = useRef(false)

  // 切换对话、请求重复、或内容变化时，重置打字进度
  useEffect(() => {
    setVisible(0)
    doneRef.current = false
  }, [event.id, repeatToken, event.content])

  // 逐字推进（仅 speaking 时）
  useEffect(() => {
    if (status !== 'speaking') return
    if (visible >= event.content.length) return
    const t = setTimeout(() => setVisible((c) => c + 1), TYPE_SPEED_MS)
    return () => clearTimeout(t)
  }, [status, visible, event.content])

  // 打字完成 → 通知状态机（仅触发一次）
  useEffect(() => {
    if (status === 'speaking' && visible >= event.content.length && !doneRef.current) {
      doneRef.current = true
      dispatch({ type: 'DIALOGUE_DONE' })
    }
  }, [status, visible, event.content.length, dispatch])

  // 只有"自然打完"才显示全文；打断时冻结在已打出的字数，剩余不露出
  const showFull = status === 'done'
  const isInterrupted = status === 'interrupted'
  const text = showFull ? event.content : event.content.slice(0, visible)
  const isPaused = status === 'paused'

  return (
    <div className="dialogue-bubble npc">
      <div className="speaker">{event.speakerName}</div>
      <div className="bubble-text">
        {text}
        {showFull && <span className="cursor-final"></span>}
        {!showFull && !isInterrupted && <span className="cursor">▋</span>}
        {isInterrupted && <span className="interrupted-cursor">—</span>}
      </div>
      {isPaused && <div className="paused-hint">⏸ 已暂停 — 点击「继续」恢复</div>}
      {isInterrupted && <div className="interrupted-hint">✋ 被打断（未说完）</div>}
    </div>
  )
}
