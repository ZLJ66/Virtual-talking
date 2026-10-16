import { GameProvider, useGame } from './state/gameContext'
import { SetupScreen } from './components/SetupScreen'
import { StoryScreen } from './components/StoryScreen'
import './App.css'

function Game() {
  const { state } = useGame()
  if (state.phase === 'setup') return <SetupScreen />
  return <StoryScreen />
}

export default function App() {
  return (
    <GameProvider>
      <Game />
    </GameProvider>
  )
}
