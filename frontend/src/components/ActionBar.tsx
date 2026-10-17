// 动作栏：打断 / 暂停 / 继续 / 请求重复 / 地点选择
//
// 阶段 A 关键变更：
//   「前往下一场景」→「去别的地方」
//   切换不再由系统判定完成度后推送，而是玩家的主动选择。
//   这是消除"关卡感"的根本机制（世界层设计 5.1）。
//
// 快捷键：Alt+I 打断 / Alt+P 暂停 / Alt+C 继续 / Alt+R 请求重复

import { useEffect, useState } from 'react'
import { useGame } from '../state/gameContext'
import { TIME_SLOT_LABELS_ZH, formatTime, isOpenAt } from '../types/world'

export function ActionBar() {
  const { state, dispatch, moveTo, waitHere } = useGame()
  const { dialogue, player, world, moving } = state
  const [showDestinations, setShowDestinations] = useState(false)

  const canInterrupt =
    dialogue.status === 'speaking' || dialogue.status === 'paused'
  const canPause = dialogue.status === 'speaking'
  const canResume = dialogue.status === 'paused'
  const canRepeat = dialogue.status === 'done' || dialogue.status === 'interrupted'

  // 可达地点（由当前地点的 connections 决定，不是固定"下一关"）
  const currentLoc = world?.locations.find((l) => l.id === player?.location)
  const destinations =
    world?.locations.filter((l) => currentLoc?.connections.includes(l.id)) ?? []

  // 全局键盘快捷键：仅在按钮可用时触发
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // 仅响应 Alt 组合，忽略 Ctrl/Meta（避免与输入框和其他快捷键冲突）
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

  const handleMove = (targetId: string) => {
    setShowDestinations(false)
    void moveTo(targetId)
  }

  return (
    <>
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

        <span className="action-divider" />

        <button
          type="button"
          className="action-btn primary"
          onClick={() => setShowDestinations((s) => !s)}
          disabled={moving || destinations.length === 0}
          title="选择要去的地方"
        >
          🚶 去别的地方
        </button>
        <button
          type="button"
          className="action-btn"
          onClick={() => void waitHere()}
          disabled={moving}
          title="在原地等一会儿，时间会推进一个时段"
        >
          ⏳ 等一会儿
        </button>
      </div>

      {showDestinations && player && (
        <div className="destination-panel">
          <div className="destination-header">
            <span>
              当前：{currentLoc?.name}　{formatTime(player.time)}
            </span>
            <button
              type="button"
              className="ghost-btn"
              onClick={() => setShowDestinations(false)}
            >
              取消
            </button>
          </div>
          <ul className="destination-list">
            {destinations.map((loc) => {
              const open = isOpenAt(loc, player.time.slot)
              const npc = world?.npcs.find((n) => n.id === loc.resident_npcs[0])
              return (
                <li key={loc.id}>
                  <button
                    type="button"
                    className={`destination-item ${open ? '' : 'closed'}`}
                    onClick={() => handleMove(loc.id)}
                    disabled={moving}
                  >
                    <span className="dest-name">{loc.name}</span>
                    <span className="dest-en">{loc.name_en}</span>
                    {npc && <span className="dest-npc">{npc.name}</span>}
                    <span className="dest-cost">
                      {loc.travel_cost > 0
                        ? `路程 ${loc.travel_cost} 时段`
                        : '就在旁边'}
                    </span>
                    {!open && (
                      <span className="dest-closed">
                        {loc.open_hours[0]}:00–{loc.open_hours[1]}:00
                      </span>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
          <p className="destination-hint">
            移动会消耗时间（对话不消耗）。现在是{player.time.slot && TIME_SLOT_LABELS_ZH[player.time.slot]}。
          </p>
        </div>
      )}
    </>
  )
}
