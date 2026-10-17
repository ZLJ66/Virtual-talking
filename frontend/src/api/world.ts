// 世界层 API 调用
// 与后端 /api/world、/api/move、/api/wait 对接

import type { MoveResult, PlayerState, WorldResponse } from '../types/world'

const API_BASE = 'http://localhost:8000'

/** 拉取世界定义 + 初始玩家状态 */
export async function fetchWorld(): Promise<WorldResponse> {
  const res = await fetch(`${API_BASE}/api/world`)
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`获取世界数据失败 (${res.status}): ${err}`)
  }
  return res.json() as Promise<WorldResponse>
}

/** 移动到目标地点。**这是唯一会推进时间的操作之一。** */
export async function fetchMove(
  playerState: PlayerState,
  target: string,
): Promise<MoveResult> {
  const res = await fetch(`${API_BASE}/api/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ player_state: playerState, target }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`移动失败 (${res.status}): ${err}`)
  }
  return res.json() as Promise<MoveResult>
}

/** 原地等待：消耗 1 个时段，世界推进一拍 */
export async function fetchWait(playerState: PlayerState): Promise<MoveResult> {
  const res = await fetch(`${API_BASE}/api/wait`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ player_state: playerState }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`等待失败 (${res.status}): ${err}`)
  }
  return res.json() as Promise<MoveResult>
}
