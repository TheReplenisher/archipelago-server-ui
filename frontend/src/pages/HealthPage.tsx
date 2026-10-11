import { Alert, Badge, Card, Group, Progress, Stack, Table, Text, Title } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { getHealthDetails, type HealthDetails } from '../api/client'

const REFRESH_MS = 10_000

function gigabytes(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`
}

const serviceLabel = { web: 'Web', worker: 'Worker', server: 'Server' }

/** Whether each service is up, ports, disk use, the AP version and the isolation mode
 * (DESIGN.md §7). Refreshes every few seconds. */
export function HealthPage() {
  const [health, setHealth] = useState<HealthDetails | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    getHealthDetails(controller.signal)
      .then((h) => {
        setHealth(h)
        setError(null)
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    const timer = setTimeout(() => setVersion((v) => v + 1), REFRESH_MS)
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [version])

  return (
    <Stack maw={960}>
      <Title order={2}>Health</Title>
      {error && (
        <Alert color="red" title="The web service isn't answering">
          {error}
        </Alert>
      )}
      {health?.isolation_warning && (
        <Alert color="orange" icon={<IconAlertTriangle />} title="Reduced isolation">
          {health.isolation_warning}
        </Alert>
      )}
      {health && (
        <>
          <Card withBorder>
            <Stack gap="xs">
              <Text fw={500}>Services</Text>
              {health.services.map((s) => (
                <Group key={s.name} justify="space-between" wrap="nowrap">
                  <Text size="sm">
                    <b>{serviceLabel[s.name]}</b>: {s.detail}
                  </Text>
                  <Badge color={s.up ? 'green' : 'red'}>{s.up ? 'Up' : 'Down'}</Badge>
                </Group>
              ))}
            </Stack>
          </Card>
          <Card withBorder>
            <Table verticalSpacing={4}>
              <Table.Tbody>
                <Table.Tr>
                  <Table.Th w={220}>Archipelago Server UI</Table.Th>
                  <Table.Td>v{health.version}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>Archipelago</Table.Th>
                  <Table.Td>{health.archipelago_version ?? 'unknown'}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>Isolation</Table.Th>
                  <Table.Td>{health.isolation}</Table.Td>
                </Table.Tr>
                {health.ports.map((p) => (
                  <Table.Tr key={p.name}>
                    <Table.Th>{p.name} port</Table.Th>
                    <Table.Td>{p.port ?? 'not set'}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
          <Card withBorder>
            <Stack gap="sm">
              <Text fw={500}>Disk use</Text>
              {health.disks.map((d) => (
                <Stack key={d.name} gap={2}>
                  <Group justify="space-between">
                    <Text size="sm">
                      {d.name}{' '}
                      <Text span c="dimmed">
                        ({d.path})
                      </Text>
                    </Text>
                    <Text size="sm">
                      {gigabytes(d.free)} free of {gigabytes(d.total)}
                    </Text>
                  </Group>
                  <Progress
                    value={(d.used / d.total) * 100}
                    color={d.free / d.total < 0.1 ? 'red' : 'blue'}
                    aria-label={`${d.name} disk use`}
                  />
                </Stack>
              ))}
            </Stack>
          </Card>
        </>
      )}
    </Stack>
  )
}
