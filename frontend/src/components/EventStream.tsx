// 事件时间线：按顺序渲染所有已生效事件
// 旁白按 narrationLang 显示中文/英文/双语；玩家输入显示为右侧气泡；NPC 对话显示为左侧气泡
// 自动滚动：新事件加入时强制滚到底（第一时间看到新内容以便打断）；
//           打字机推进时若用户在底部附近则跟随，用户向上查看历史时不强制拉回。

import { useEffect, useRef } from 'react'
import { useGame } from '../state/gameContext'
import type { GameEvent, NarrationLanguage } from '../types'
import { DialogueBubble } from './DialogueBubble'

interface EventItemProps {
  event: GameEvent
  lang: NarrationLanguage
  active: boolean
}

function NarrationText({ zh, en, lang }: { zh: string; en: string; lang: NarrationLanguage }) {
  return (
    <div className="narration">
      {lang === 'zh' && <p className="narration-zh">{zh}</p>}
      {lang === 'en' && <p className="narration-en">{en}</p>}
      {lang === 'both' && (
        <>
          <p className="narration-en">{en}</p>
          <p className="narration-zh">{zh}</p>
        </>
      )}
    </div>
  )
}

function EventItem({ event, lang, active }: EventItemProps) {
  switch (event.kind) {
    case 'scene_intro':
      return (
        <div className="scene-intro">
          <div className="scene-badge">场景</div>
          <h2 className="scene-title">{event.title}</h2>
          <p className="scene-desc">{event.description}</p>
        </div>
      )
    case 'narration':
      return <NarrationText zh={event.zh} en={event.en} lang={lang} />
    case 'npc_dialogue':
      // 当前活跃对话用打字机，其余静态显示全文
      return active ? (
        <DialogueBubble event={event} />
      ) : (
        <div className="dialogue-bubble npc static">
          <div className="speaker">{event.speakerName}</div>
          <div className="bubble-text">{event.content}</div>
        </div>
      )
    case 'player_input':
      return (
        <div className="player-input-block">
          {event.speech && (
            <div className="dialogue-bubble player">
              <div className="speaker">你</div>
              <div className="bubble-text">{event.speech}</div>
            </div>
          )}
          {event.action && (
            <div className="action-line">🎬 {event.action}</div>
          )}
        </div>
      )
    case 'action_result':
      return <NarrationText zh={event.zh} en={event.en} lang={lang} />
    case 'scene_transition':
      return (
        <div className="scene-transition">
          <span className="arrow">→</span> {event.summary}
        </div>
      )
    default:
      return null
  }
}

/** 滚动到底部的阈值（距底部小于此值视为“在底部”） */
const BOTTOM_THRESHOLD = 80

export function EventStream() {
  const { state } = useGame()
  const activeId = state.dialogue.eventId
  // 内容容器（.event-stream）的 ref；其父元素 .event-scroll 才是滚动容器
  const contentRef = useRef<HTMLDivElement>(null)
  // 记录用户是否停留在底部，用于决定打字推进时是否跟随滚动
  const atBottomRef = useRef(true)

  const scrollEl = (): HTMLElement | null =>
    contentRef.current?.parentElement ?? null

  const scrollToBottom = () => {
    const el = scrollEl()
    if (el) el.scrollTop = el.scrollHeight
  }

  // 监听滚动：记录用户当前位置（在底部附近则视为“跟随”）
  useEffect(() => {
    const el = scrollEl()
    if (!el) return
    const onScroll = () => {
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight
      atBottomRef.current = dist < BOTTOM_THRESHOLD
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  // 新事件加入 → 强制滚到底（确保第一时间看到新内容，抓住打断时机）
  const eventCount = state.events.length
  useEffect(() => {
    scrollToBottom()
    atBottomRef.current = true
  }, [eventCount])

  // 内容高度变化（打字机逐字推进、旁白展开等）→ 若在底部附近则跟随
  useEffect(() => {
    const content = contentRef.current
    const scroll = scrollEl()
    if (!content || !scroll) return
    const ro = new ResizeObserver(() => {
      if (atBottomRef.current) scroll.scrollTop = scroll.scrollHeight
    })
    ro.observe(content)
    return () => ro.disconnect()
  }, [])

  return (
    <div className="event-stream" ref={contentRef}>
      {state.events.map((ev) => (
        <EventItem
          key={ev.id}
          event={ev}
          lang={state.narrationLang}
          active={ev.id === activeId && ev.kind === 'npc_dialogue'}
        />
      ))}
      {state.storyComplete && (
        <div className="story-end">
          <h3>🎉 故事完成</h3>
          <p>你顺利度过了在英国的第一天。想再体验一次，可以点击右上角的「重新开始」。</p>
        </div>
      )}
    </div>
  )
}
