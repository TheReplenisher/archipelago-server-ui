import { Badge, Card, Group, Text } from '@mantine/core'
import { useEffect, useState } from 'react'
import { getHealth, type Health } from '../api/client'

type State = { kind: 'loading' } | { kind: 'ok'; health: Health } | { kind: 'error' }

export function BackendStatus() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal)
      .then((health) => setState({ kind: 'ok', health }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ kind: 'error' })
      })
    return () => controller.abort()
  }, [])

  return (
    <Card withBorder>
      <Group justify="space-between">
        <Text fw={500}>Backend</Text>
        {state.kind === 'loading' && <Badge color="gray">Checking…</Badge>}
        {state.kind === 'ok' && <Badge color="green">Online · v{state.health.version}</Badge>}
        {state.kind === 'error' && <Badge color="red">Unreachable</Badge>}
      </Group>
    </Card>
  )
}
