import { Alert, Badge, Card, Group, ScrollArea, Stack, Text } from '@mantine/core'
import { useEffect, useRef, useState } from 'react'
import {
  getPlayerFeed,
  ITEM_PROGRESSION,
  ITEM_TRAP,
  ITEM_USEFUL,
  type FeedEntry,
  type FeedPart,
} from '../api/client'

const POLL_MS = 3000
const MAX_SHOWN = 500

function itemColor(flags = 0): string | undefined {
  if (flags & ITEM_PROGRESSION) return 'grape'
  if (flags & ITEM_TRAP) return 'red'
  if (flags & ITEM_USEFUL) return 'blue'
  return undefined
}

function Part({ part }: { part: FeedPart }) {
  if (part.kind === 'player')
    return (
      <Text span fw={600}>
        {part.text}
      </Text>
    )
  if (part.kind === 'item')
    return (
      <Text span fw={500} c={itemColor(part.flags)}>
        {part.text}
      </Text>
    )
  if (part.kind === 'location' || part.kind === 'entrance')
    return (
      <Text span c="teal">
        {part.text}
      </Text>
    )
  return <Text span>{part.text}</Text>
}

/** What the server tells every player (#35): item sends, chat, joins, goals. Never hints,
 * which stay with the players involved, and never the admin's own feed. */
export function PlayerFeed() {
  const [entries, setEntries] = useState<FeedEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const last = useRef(0)

  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const controller = new AbortController()
    const poll = async () => {
      try {
        const page = await getPlayerFeed(last.current, controller.signal)
        if (stopped) return
        if (page.last < last.current) setEntries([]) // a new game started a new feed
        last.current = page.last
        if (page.entries.length)
          setEntries((old) => [...page.entries.reverse(), ...old].slice(0, MAX_SHOWN))
        setError(null)
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : String(e))
      }
      if (!stopped) timer = setTimeout(poll, POLL_MS)
    }
    void poll()
    return () => {
      stopped = true
      clearTimeout(timer)
      controller.abort()
    }
  }, [])

  return (
    <Stack gap="xs">
      {error && <Alert color="orange">{error}</Alert>}
      {entries.length === 0 && !error && (
        <Text size="sm" c="dimmed">
          Nothing yet. Item sends, chat and goals show up here as they happen.
        </Text>
      )}
      {entries.length > 0 && (
        <Card withBorder padding="xs">
          <ScrollArea.Autosize mah={480}>
            <Stack gap={4} aria-label="Feed entries">
              {entries.map((entry) => (
                <Group key={entry.id} gap={6} wrap="nowrap" align="flex-start">
                  <Text size="xs" c="dimmed" miw={64}>
                    {new Date(entry.at * 1000).toLocaleTimeString()}
                  </Text>
                  {entry.type === 'Goal' && (
                    <Badge size="xs" color="green">
                      goal
                    </Badge>
                  )}
                  <Text size="sm">
                    {entry.parts.map((part, i) => (
                      <Part key={i} part={part} />
                    ))}
                  </Text>
                </Group>
              ))}
            </Stack>
          </ScrollArea.Autosize>
        </Card>
      )}
    </Stack>
  )
}
