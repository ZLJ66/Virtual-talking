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

  // 在场的人 = 当地常驻 + 跟随玩家的同伴（与后端 buildPresentNPCs 逻辑一致）
  const presentNpcs = (() => {
    if (!world || !player || !currentLoc) return []
    const byId = new Map(world.npcs.map((n) => [n.id, n]))
    const list: { npc: (typeof world.npcs)[number]; isCompanion: boolean }[] = []
    const seen = new Set<string>()
    for (const id of currentLoc.resident_npcs ?? []) {
      const npc = byId.get(id)
      if (npc && !seen.has(id)) {
        seen.add(id)
        list.push({ npc, isCompanion: false })
      }
    }
    for (const id of player.companions ?? []) {
      const npc = byId.get(id)
      if (npc && !seen.has(id)) {
        seen.add(id)
        list.push({ npc, isCompanion: true })
      }
    }
    return list
  })()

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
          <span className="status-goal">
            主线：{state.progress?.title ?? world.mainline.title}
            {state.progress && (
              <span className="status-progress">
                {' '}
                {state.progress.done}/{state.progress.total}
              </span>
            )}
            {state.progress?.missed && (
              <span className="status-missed">（已逾期）</span>
            )}
          </span>
        )}
        {player && player.companions.length > 0 && (
          <span className="status-companion">
            同行：
            {player.companions
              .map((id) => world?.npcs.find((n) => n.id === id)?.name ?? id)
              .join('、')}
          </span>
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

            {presentNpcs.length > 0 && (
              <>
                <dt>在场</dt>
                <dd>
                  {presentNpcs
                    .map(
                      ({ npc, isCompanion }) =>
                        `${npc.name}（${npc.role}${isCompanion ? '，同行' : ''}）`,
                    )
                    .join('；')}
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
              {state.progress ? (
                <>
                  {state.progress.done}/{state.progress.total}
                  {state.progress.done_titles.length > 0 && (
                    <>　已完成：{state.progress.done_titles.join('、')}</>
                  )}
                  {state.progress.pending_titles.length > 0 && (
                    <>　待办：{state.progress.pending_titles.join('、')}</>
                  )}
                </>
              ) : (
                '（尚未开始）'
              )}
            </dd>

            {/* 判定器算出的「现在能办什么、还差什么」。
                不显示内部 fact id——玩家看到的是「材料还差 share code」，
                而不是 pre_enrolment_submitted: false。 */}
            {state.mainlineLines.length > 0 && (
              <>
                <dt>现在能做的</dt>
                <dd style={{ whiteSpace: 'pre-line' }}>
                  {state.mainlineLines.join('\n')}
                </dd>
              </>
            )}

            {presentNpcs
              .filter(({ npc }) => player.npc_states[npc.id])
              .map(({ npc }) => (
                <div key={npc.id} style={{ display: 'contents' }}>
                  <dt>{npc.name} 记得</dt>
                  <dd>
                    {[
                      ...player.npc_states[npc.id].impression_tags,
                      ...player.npc_states[npc.id].memories,
                    ].join('；') || '（还不熟悉）'}
                  </dd>
                </div>
              ))}
          </dl>
        </div>
      )}
    </div>
  )
}
