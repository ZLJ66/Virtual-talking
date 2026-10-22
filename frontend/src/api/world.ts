// 世界层 API 调用
// 与后端 /api/world、/api/move、/api/wait、/api/judge 对接

import type {
  JudgeResult,
  MoveResult,
  PlayerState,
  WorldResponse,
} from '../types/world'

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

/**
 * 原地等待：消耗时段，世界推进。
 *
 * slots=1 是「等一会儿」；大到跨日就是「睡一觉」。
 */
export async function fetchWait(
  playerState: PlayerState,
  slots = 1,
): Promise<MoveResult> {
  const res = await fetch(`${API_BASE}/api/wait`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ player_state: playerState, slots }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`等待失败 (${res.status}): ${err}`)
  }
  return res.json() as Promise<MoveResult>
}

/**
 * 把 AI 提议的世界变更交给后端判定器裁决。
 *
 * **这是事实进入玩家状态的唯一入口。**
 * 前端不再自己写 set_fact——判定规则（地点对不对、材料带没带、
 * 前置步骤做没做、窗口过没过）只能有一份实现，放在后端。
 * 前端复制一份的话，两边必然漂移，而且前端那份很容易被绕过。
 */
export async function fetchJudge(
  playerState: PlayerState,
  worldChanges: Record<string, unknown>,
): Promise<JudgeResult> {
  const res = await fetch(`${API_BASE}/api/judge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      player_state: playerState,
      world_changes: worldChanges,
    }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`判定失败 (${res.status}): ${err}`)
  }
  return res.json() as Promise<JudgeResult>
}
