import { Alert, Badge, Button, Card, Group, Stack, Text } from '@mantine/core'
import { useEffect, useState } from 'react'
import { getGame, runGameAction, type Game, type GameAction, type GameState } from '../api/client'

const stateInfo: Record<GameState, { label: string; color: string; help: string }> = {
  open: { label: 'Open', color: 'green', help: 'Uploads are being accepted.' },
  locked: {
    label: 'Locked',
    color: 'yellow',
    help: 'Uploads are frozen for review before generating.',
  },
  generating: { label: 'Generating', color: 'blue', help: 'The multiworld is being generated.' },
  generated: {
    label: 'Generated',
    color: 'teal',
    help: 'Ready to start. The server is stopped.',
  },
  running: { label: 'Running', color: 'grape', help: 'The server is up and players can join.' },
  archived: { label: 'Archived', color: 'gray', help: 'This game has ended.' },
}

const actionLabels: Record<GameAction, string> = {
  lock: 'Lock uploads',
  unlock: 'Unlock uploads',
}

export function CurrentGame() {
  const [game, setGame] = useState<Game | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getGame(controller.signal)
      .then(setGame)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [])

  const run = async (action: GameAction) => {
    setBusy(true)
    setError(null)
    try {
      setGame(await runGameAction(action))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const info = game ? stateInfo[game.state] : null
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={500}>Current game{game ? ` #${game.id}` : ''}</Text>
          {info && <Badge color={info.color}>{info.label}</Badge>}
        </Group>
        {info && (
          <Text size="sm" c="dimmed">
            {info.help}
          </Text>
        )}
        {error && (
          <Alert color="red" title="Something went wrong">
            {error}
          </Alert>
        )}
        {game && game.actions.length > 0 && (
          <Group>
            {game.actions.map((action) => (
              <Button key={action} variant="light" loading={busy} onClick={() => run(action)}>
                {actionLabels[action]}
              </Button>
            ))}
          </Group>
        )}
      </Stack>
    </Card>
  )
}
