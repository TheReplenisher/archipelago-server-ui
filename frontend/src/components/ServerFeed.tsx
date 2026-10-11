import { Badge, Card, Code, Group, Stack, Text } from '@mantine/core'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { serverFeedUrl } from '../api/client'

/** Lines kept in the page; the server sends the last 500 on connecting. */
const MAX_LINES = 2000
const RETRY_MS = 2000

type Status = 'connecting' | 'live' | 'reconnecting'

const statusBadge: Record<Status, { label: string; color: string }> = {
  connecting: { label: 'Connecting', color: 'gray' },
  live: { label: 'Live', color: 'green' },
  reconnecting: { label: 'Reconnecting', color: 'yellow' },
}

interface FeedMessage {
  /** The lines replace what's shown: the scrollback, on connecting or a new log. */
  reset: boolean
  lines: string[]
}

/** MultiServer's own output, live, including the console's replies (admin only: it holds
 * the room password). It follows the newest line unless the admin scrolls up to read. */
export function ServerFeed() {
  const [lines, setLines] = useState<string[]>([])
  const [status, setStatus] = useState<Status>('connecting')
  const box = useRef<HTMLPreElement>(null)
  const following = useRef(true)

  useEffect(() => {
    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let stopped = false
    const connect = () => {
      socket = new WebSocket(serverFeedUrl())
      socket.onopen = () => setStatus('live')
      socket.onmessage = (event: MessageEvent<string>) => {
        const message = JSON.parse(event.data) as FeedMessage
        setLines((old) =>
          (message.reset ? message.lines : [...old, ...message.lines]).slice(-MAX_LINES),
        )
      }
      socket.onclose = () => {
        if (stopped) return
        setStatus('reconnecting')
        retry = setTimeout(connect, RETRY_MS)
      }
    }
    connect()
    return () => {
      stopped = true
      clearTimeout(retry)
      socket?.close()
    }
  }, [])

  useLayoutEffect(() => {
    const el = box.current
    if (el && following.current) el.scrollTop = el.scrollHeight
  }, [lines])

  const onScroll = () => {
    const el = box.current
    if (el) following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
  }

  const badge = statusBadge[status]
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={500}>Server feed</Text>
          <Badge color={badge.color}>{badge.label}</Badge>
        </Group>
        <Code
          block
          ref={box}
          onScroll={onScroll}
          h={320}
          style={{ overflow: 'auto' }}
          aria-label="Server feed"
        >
          {lines.length > 0 ? lines.join('\n') : 'No server output yet.'}
        </Code>
        <Text size="xs" c="dimmed">
          MultiServer's own output, with the console's replies. It shows the room password, so it's
          for the admin only.
        </Text>
      </Stack>
    </Card>
  )
}
