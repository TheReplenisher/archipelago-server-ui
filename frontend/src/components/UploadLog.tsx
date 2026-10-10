import { Alert, Anchor, Badge, Card, Stack, Table, Text } from '@mantine/core'
import { useEffect, useState } from 'react'
import { UploadLogModal } from './UploadLogModal'
import { listUploadLog, type LogEntry } from '../api/client'

/** Every upload, YAML and apworld, newest first; click one for its full log. */
export function UploadLog() {
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<LogEntry | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    listUploadLog(controller.signal)
      .then(setEntries)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [open])

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Text fw={500}>Upload log</Text>
        {error && <Alert color="red">{error}</Alert>}
        {entries.length === 0 ? (
          <Text size="sm" c="dimmed">
            No uploads yet.
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={480} mah={320}>
            <Table verticalSpacing={4}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>When</Table.Th>
                  <Table.Th>File</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Code</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {entries.map((e) => (
                  <Table.Tr key={e.key}>
                    <Table.Td>
                      <Text size="sm">{new Date(e.uploaded_at).toLocaleString()}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Anchor component="button" size="sm" onClick={() => setOpen(e)}>
                        {e.filename}
                      </Anchor>{' '}
                      <Badge size="xs" variant="outline" color="gray">
                        {e.kind}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{e.status}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" c={e.error_code ? 'red' : 'dimmed'}>
                        {e.error_code ?? '—'}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Stack>
      {open && <UploadLogModal kind={open.kind} id={open.id} onClose={() => setOpen(null)} />}
    </Card>
  )
}
