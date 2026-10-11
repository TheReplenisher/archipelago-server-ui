import { Alert, Badge, Button, Card, Code, Group, Stack, Text } from '@mantine/core'
import { useEffect, useState } from 'react'
import {
  getGame,
  getServer,
  listGenerations,
  runGameAction,
  saveServer,
  type Game,
  type GameAction,
  type GameState,
  type Generation,
  type ServerStatus,
} from '../api/client'
import { PatchFiles } from './PatchFiles'

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
  generate: 'Generate',
  'discard-output': 'Discard output',
  start: 'Start server',
  stop: 'Stop server',
}

/** What MultiServer is doing, while the game is Running. */
function ServerLine({ server }: { server: ServerStatus }) {
  if (!server.reachable)
    return (
      <Text size="sm" c="red">
        The server service isn't answering.
      </Text>
    )
  if (server.state === 'crashed')
    return (
      <Alert color="red" title={`The server stopped unexpectedly (exit code ${server.exit_code})`}>
        <Code block mah={200} style={{ overflow: 'auto' }}>
          {server.log_tail.join('\n')}
        </Code>
      </Alert>
    )
  return (
    <Text size="sm">
      Server {server.state}
      {server.state === 'running' && server.port ? ` on port ${server.port}` : ''}
      {server.multidata ? ` (${server.multidata})` : ''}
    </Text>
  )
}

const POLL_MS = 2000

/** The latest generation run: its result, or what went wrong and which upload AP blamed. */
function LatestGeneration({ generation }: { generation: Generation }) {
  if (generation.status === 'running')
    return (
      <Text size="sm" c="blue">
        Generation running since {new Date(generation.started_at).toLocaleTimeString()}
      </Text>
    )
  if (generation.status === 'ok')
    return (
      <Text size="sm">
        Generated seed {generation.seed_name} for {generation.players.length}{' '}
        {generation.players.length === 1 ? 'player' : 'players'}: {generation.players.join(', ')}
      </Text>
    )
  return (
    <Alert color="red" title="Generation failed">
      <Stack gap={4}>
        <Text size="sm">{generation.error_message}</Text>
        {generation.culprits.length > 0 && (
          <Text size="sm">
            Archipelago points at:{' '}
            {generation.culprits.map((c) => `${c.filename} (${c.slots.join(', ')})`).join('; ')}
          </Text>
        )}
        {(generation.traceback || generation.log_tail) && (
          <Code block mah={200} style={{ overflow: 'auto' }}>
            {[generation.traceback, generation.log_tail].filter(Boolean).join('\n\n')}
          </Code>
        )}
      </Stack>
    </Alert>
  )
}

export function CurrentGame() {
  const [game, setGame] = useState<Game | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [generations, setGenerations] = useState<Generation[]>([])
  const [server, setServer] = useState<ServerStatus | null>(null)
  const [version, setVersion] = useState(0) // bump to reload

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([getGame(controller.signal), listGenerations(controller.signal)])
      .then(async ([game, generations]) => {
        setGame(game)
        setGenerations(generations)
        setServer(game.state === 'running' ? await getServer(controller.signal) : null)
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [version])

  // While generating, or while the server comes up or goes down, poll until it settles.
  const settling =
    game?.state === 'generating' || server?.state === 'starting' || server?.state === 'stopping'
  useEffect(() => {
    if (!settling) return
    const timer = setInterval(() => setVersion((v) => v + 1), POLL_MS)
    return () => clearInterval(timer)
  }, [settling])

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await saveServer()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const run = async (action: GameAction) => {
    setBusy(true)
    setError(null)
    try {
      await runGameAction(action)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      setVersion((v) => v + 1)
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
        {server ? (
          <ServerLine server={server} />
        ) : (
          generations[0] && <LatestGeneration generation={generations[0]} />
        )}
        {(game?.state === 'generated' || game?.state === 'running') && (
          <PatchFiles key={generations[0]?.id} />
        )}
        {game && game.actions.length > 0 && (
          <Group>
            {game.actions.map((action) => (
              <Button key={action} variant="light" loading={busy} onClick={() => run(action)}>
                {actionLabels[action]}
              </Button>
            ))}
            {server?.state === 'running' && (
              <Button variant="subtle" loading={busy} onClick={save}>
                Save
              </Button>
            )}
          </Group>
        )}
      </Stack>
    </Card>
  )
}
