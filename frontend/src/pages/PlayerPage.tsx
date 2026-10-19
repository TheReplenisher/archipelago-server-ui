import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  PasswordInput,
  ScrollArea,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { IconPlugConnectedX } from '@tabler/icons-react'
import { useEffect, useState, type FormEvent } from 'react'
import { PlayerUploads } from '../components/PlayerUploads'
import {
  ApiError,
  getPlayerGame,
  getSlotView,
  ITEM_PROGRESSION,
  ITEM_TRAP,
  ITEM_USEFUL,
  slotLogin,
  slotLogout,
  type PlayerGame,
  type SlotView,
} from '../api/client'

const POLL_MS = 3000

type Screen = 'loading' | 'login' | 'stopped' | 'view'

/** progression / useful / trap, as AP flags them. */
function Flags({ flags }: { flags: number }) {
  return (
    <>
      {flags & ITEM_PROGRESSION ? (
        <Badge size="xs" color="grape" variant="light">
          progression
        </Badge>
      ) : null}
      {flags & ITEM_USEFUL ? (
        <Badge size="xs" color="blue" variant="light">
          useful
        </Badge>
      ) : null}
      {flags & ITEM_TRAP ? (
        <Badge size="xs" color="red" variant="light">
          trap
        </Badge>
      ) : null}
    </>
  )
}

function ItemName({ item, flags }: { item: string; flags: number }) {
  return (
    <Group gap={4} wrap="nowrap">
      <Text size="sm">{item}</Text>
      <Flags flags={flags} />
    </Group>
  )
}

/** What a player sees while the server isn't running (conne's wording, 2026-10-11). */
function Stopped({ onRetry }: { onRetry?: () => void }) {
  return (
    <Card withBorder maw={520}>
      <Stack align="center" gap="sm" py="md">
        <IconPlugConnectedX size={40} stroke={1.5} />
        <Title order={3}>The server is stopped</Title>
        <Text c="dimmed" ta="center">
          Please reach out to your admin. This page picks up again as soon as the server is back.
        </Text>
        {onRetry && (
          <Button variant="subtle" onClick={onRetry}>
            Back to the login
          </Button>
        )}
      </Stack>
    </Card>
  )
}

function Login({ onLoggedIn, onStopped }: { onLoggedIn: () => void; onStopped: () => void }) {
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await slotLogin(name.trim(), password)
      onLoggedIn()
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) onStopped()
      else if (e instanceof ApiError && e.status === 401)
        setError('That slot name or room password is wrong.')
      else setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card withBorder maw={420}>
      <form onSubmit={submit}>
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            Log in with your slot name and the room password, as you would in your game client.
            Leave the password empty if the room has none.
          </Text>
          <TextInput
            label="Slot name"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            maxLength={16}
            required
            autoComplete="username"
          />
          <PasswordInput
            label="Room password"
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            autoComplete="current-password"
          />
          {error && <Alert color="red">{error}</Alert>}
          <Button type="submit" loading={busy} w="fit-content">
            Log in
          </Button>
        </Stack>
      </form>
    </Card>
  )
}

function Received({ view }: { view: SlotView }) {
  if (view.received.length === 0) return <Text c="dimmed">Nothing received yet.</Text>
  return (
    <Table.ScrollContainer minWidth={420}>
      <Table verticalSpacing={4}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Item</Table.Th>
            <Table.Th>From</Table.Th>
            <Table.Th>Found at</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {[...view.received].reverse().map((r, i) => (
            <Table.Tr key={view.received.length - i}>
              <Table.Td>
                <ItemName item={r.item} flags={r.flags} />
              </Table.Td>
              <Table.Td>{r.player}</Table.Td>
              <Table.Td>{r.location}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}

const ruleText: Record<SlotView['unreceived_rule'], string> = {
  enabled: '',
  goal: 'Shown once you reach your goal (this room’s !remaining setting).',
  disabled: 'This room doesn’t show the items still out there (its !remaining setting).',
  unavailable: 'Not available for this game: it was generated before this list existed.',
}

function Unreceived({ view }: { view: SlotView }) {
  if (view.unreceived === null) return <Text c="dimmed">{ruleText[view.unreceived_rule]}</Text>
  if (view.unreceived.length === 0) return <Text c="dimmed">You have everything.</Text>
  return (
    <Stack gap={4}>
      <Text size="xs" c="dimmed">
        Your items still somewhere in the multiworld. Where they are isn’t shown.
      </Text>
      <Table verticalSpacing={4}>
        <Table.Tbody>
          {view.unreceived.map((u) => (
            <Table.Tr key={u.item}>
              <Table.Td>
                <ItemName item={u.item} flags={u.flags} />
              </Table.Td>
              <Table.Td>
                <Text size="sm" c="dimmed" ta="right">
                  {u.count > 1 ? `×${u.count}` : ''}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  )
}

function Unchecked({ view }: { view: SlotView }) {
  const [filter, setFilter] = useState('')
  const shown = view.unchecked.filter((l) => l.toLowerCase().includes(filter.toLowerCase()))
  if (view.unchecked.length === 0) return <Text c="dimmed">Every location is checked.</Text>
  return (
    <Stack gap="xs">
      <TextInput
        placeholder="Filter locations"
        value={filter}
        onChange={(e) => setFilter(e.currentTarget.value)}
        maw={320}
      />
      <ScrollArea.Autosize mah={480}>
        <Stack gap={2}>
          {shown.map((l) => (
            <Text size="sm" key={l}>
              {l}
            </Text>
          ))}
        </Stack>
      </ScrollArea.Autosize>
    </Stack>
  )
}

function Hints({ view }: { view: SlotView }) {
  if (view.hints.length === 0) return <Text c="dimmed">No hints yet.</Text>
  return (
    <Table.ScrollContainer minWidth={560}>
      <Table verticalSpacing={4}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Item</Table.Th>
            <Table.Th>For</Table.Th>
            <Table.Th>At</Table.Th>
            <Table.Th>In the world of</Table.Th>
            <Table.Th>Status</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {view.hints.map((h, i) => (
            <Table.Tr key={i}>
              <Table.Td>
                <ItemName item={h.item} flags={h.flags} />
              </Table.Td>
              <Table.Td>{h.receiving}</Table.Td>
              <Table.Td>
                {h.location}
                {h.entrance && (
                  <Text size="xs" c="dimmed">
                    via {h.entrance}
                  </Text>
                )}
              </Table.Td>
              <Table.Td>{h.finding}</Table.Td>
              <Table.Td>
                {h.found ? (
                  <Badge color="green" variant="light">
                    found
                  </Badge>
                ) : (
                  <Text size="sm">{h.status}</Text>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}

function SlotPanels({ view, onLogout }: { view: SlotView; onLogout: () => void }) {
  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={3}>{view.slot.name}</Title>
          <Text c="dimmed">{view.slot.game}</Text>
          {view.goal && <Badge color="green">Goal reached</Badge>}
          {!view.live && (
            <Badge color="orange" variant="light">
              reconnecting
            </Badge>
          )}
        </Group>
        <Button variant="subtle" onClick={onLogout}>
          Log out
        </Button>
      </Group>
      <Text size="sm" c="dimmed">
        {view.checked} of {view.locations} locations checked · {view.hint_points} hint points
      </Text>
      <Tabs defaultValue="received" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="received">Received ({view.received.length})</Tabs.Tab>
          <Tabs.Tab value="unreceived">
            Still out there
            {view.unreceived ? ` (${view.unreceived.reduce((n, u) => n + u.count, 0)})` : ''}
          </Tabs.Tab>
          <Tabs.Tab value="unchecked">Unchecked locations ({view.unchecked.length})</Tabs.Tab>
          <Tabs.Tab value="hints">Hints ({view.hints.length})</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="received" pt="sm">
          <Received view={view} />
        </Tabs.Panel>
        <Tabs.Panel value="unreceived" pt="sm">
          <Unreceived view={view} />
        </Tabs.Panel>
        <Tabs.Panel value="unchecked" pt="sm">
          <Unchecked view={view} />
        </Tabs.Panel>
        <Tabs.Panel value="hints" pt="sm">
          <Hints view={view} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}

/** A player's own slot (DESIGN.md §6): log in, then follow items, locations and hints. */
export function PlayerPage() {
  const [game, setGame] = useState<PlayerGame | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    getPlayerGame(controller.signal)
      .then(setGame)
      .catch(() => undefined)
    return () => controller.abort()
  }, [])
  return (
    <Stack maw={960}>
      <Title order={2}>Player</Title>
      {game && <PlayerUploads game={game} />}
      {game?.state === 'open' ? (
        <Text size="sm" c="dimmed">
          Once the admin starts the game, log in here with your slot name to follow your items,
          locations and hints.
        </Text>
      ) : (
        <SlotSection />
      )}
    </Stack>
  )
}

/** Log in to a slot, then follow it; or hear that the server is stopped. */
function SlotSection() {
  const [screen, setScreen] = useState<Screen>('loading')
  const [view, setView] = useState<SlotView | null>(null)
  const [loggedIn, setLoggedIn] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    getSlotView(controller.signal)
      .then((v) => {
        setView(v)
        setLoggedIn(true)
        setError(null)
        setScreen('view')
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return
        if (e instanceof ApiError && e.status === 401) {
          setLoggedIn(false)
          setScreen('login')
        } else if (e instanceof ApiError && e.status === 503) setScreen('stopped')
        else setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [version])

  // Keep the view current, and notice when a stopped server is back.
  const polling = screen === 'view' || (screen === 'stopped' && loggedIn)
  useEffect(() => {
    if (!polling) return
    const timer = setInterval(() => setVersion((v) => v + 1), POLL_MS)
    return () => clearInterval(timer)
  }, [polling])

  const logout = async () => {
    await slotLogout().catch(() => undefined)
    setLoggedIn(false)
    setView(null)
    setScreen('login')
  }

  return (
    <Stack>
      {error && <Alert color="red">{error}</Alert>}
      {screen === 'loading' && <Loader size="sm" />}
      {screen === 'login' && (
        <Login onLoggedIn={() => setVersion((v) => v + 1)} onStopped={() => setScreen('stopped')} />
      )}
      {screen === 'stopped' && (
        <Stopped onRetry={loggedIn ? undefined : () => setScreen('login')} />
      )}
      {screen === 'view' && view && <SlotPanels view={view} onLogout={logout} />}
    </Stack>
  )
}
