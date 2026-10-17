// 状态栏：时间 / 当前地点 / 旁白语言切换 / 世界状态查看 / 模式切换

import { useState } from 'react'
import { useGame } from '../state/gameContext'
import type { NarrationLanguage } from '../types'
import { formatTime } from '../types/world'
import { ModeSwitcher } from './ModeSwitcher'

const LANG_LABELS: Record<NarrationLanguage, string> = {
  both: '中英',
  zh: '中文',
  en: '英文',
}

export function StatusBar() {
  const { state, dispatch } = useGame()
  const [showWorld, setShowWorld] = useState(false)

  const player = state.player
  const world = state.world
  const currentLoc = world?.locations.find((l) => l.id === player?.location)
  const currentNpc = world?.npcs.find((n) => n.id === currentLoc?.resident_npcs[0])

  return (
    <div className="status-bar">
      <div className="status-left">
        <span className="status-scene">
          {currentLoc?.name ?? '—'}
          {player && (
            <span className="status-time">　{formatTime(player.time)}</span>
          )}
        </span>
        {world && (
          <span className="status-goal">主线：{world.mainline.title}</span>
        )}
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

      {showWorld && player && world && (
        <div className="world-popover">
          <h4>当前世界状态</h4>
          <dl className="world-grid">
            <dt>时间</dt>
            <dd>{formatTime(player.time)}</dd>

            <dt>地点</dt>
            <dd>
              {currentLoc?.name ?? player.location}
              {currentLoc?.name_en ? `（${currentLoc.name_en}）` : ''}
            </dd>

            {currentNpc && (
              <>
                <dt>在场</dt>
                <dd>
                  {currentNpc.name}（{currentNpc.role}）
                </dd>
              </>
            )}

            <dt>物品</dt>
            <dd>
              {player.inventory.length > 0 ? player.inventory.join('、') : '（空）'}
            </dd>

            <dt>已知</dt>
            <dd>
              {player.knowledge.length > 0
                ? player.knowledge.join('；')
                : '（暂无）'}
            </dd>

            <dt>主线进度</dt>
            <dd>
              {Object.entries(player.facts)
                .filter(([, v]) => v)
                .map(([k]) => k)
                .join('；') || '（尚未开始）'}
            </dd>

            {currentNpc && player.npc_states[currentNpc.id] && (
              <>
                <dt>{currentNpc.name} 记得</dt>
                <dd>
                  {[
                    ...player.npc_states[currentNpc.id].impression_tags,
                    ...player.npc_states[currentNpc.id].memories,
                  ].join('；') || '（还不熟悉）'}
                </dd>
              </>
            )}
          </dl>
        </div>
      )}
    </div>
  )
}
