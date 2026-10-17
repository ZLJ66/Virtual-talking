// 故事主页面：组合状态栏、事件流、反馈面板、动作栏与输入栏
// AI 开场和回合响应由 gameContext 中的 effect 自动触发

import { useGame } from '../state/gameContext'
import { EventStream } from './EventStream'
import { StatusBar } from './StatusBar'
import { InputBar } from './InputBar'
import { ActionBar } from './ActionBar'
import { FeedbackPanel } from './FeedbackPanel'

export function StoryScreen() {
  const { state, dispatch } = useGame()

  return (
    <div className="story-screen">
      <StatusBar />
      <div className="story-main">
        <div className="event-scroll">
          <EventStream />
        </div>
        {/* AI 加载指示器 */}
        {state.aiLoading && (
          <div className="ai-loading-bar">
            <span className="ai-loading-dot" />
            <span className="ai-loading-text">AI 正在构思…</span>
          </div>
        )}
        {/* AI 错误提示 */}
        {state.aiError && (
          <div className="ai-error-bar">
            <span className="ai-error-text">⚠️ {state.aiError}</span>
            <button
              type="button"
              className="ai-error-dismiss"
              onClick={() => dispatch({ type: 'CLEAR_ERROR' })}
            >
              ✕
            </button>
          </div>
        )}
        <div className="story-bottom">
          <FeedbackPanel />
          <div className="story-input-area">
            <ActionBar />
            <InputBar />
          </div>
        </div>
      </div>
      {state.phase === 'ended' && (
        <div className="bottom-banner">
          🎉 故事完成 — 点击「重新开始」体验新流程
        </div>
      )}
    </div>
  )
}
