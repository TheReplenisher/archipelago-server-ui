import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Code,
  Group,
  Loader,
  MultiSelect,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { useEffect, useState } from 'react'
import { getAudit, type AuditEntry, type AuditFilter } from '../api/client'

/** The facts an entry recorded, one per line: `key: value`. */
function Detail({ detail }: { detail: Record<string, unknown> | null }) {
  if (!detail) return null
  const lines = Object.entries(detail).map(
    ([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`,
  )
  return (
    <Code block fz="xs" mah={120} style={{ overflow: 'auto', whiteSpace: 'pre-wrap' }}>
      {lines.join('\n')}
    </Code>
  )
}

/** Who did what, when (#37): every admin action, newest first. */
export function AuditPage() {
  const [actions, setActions] = useState<string[]>([])
  const [failed, setFailed] = useState(false)
  const [text, setText] = useState('')
  const [q] = useDebouncedValue(text, 300)
  const [entries, setEntries] = useState<AuditEntry[] | null>(null)
  const [labels, setLabels] = useState<Record<string, string>>({})
  const [next, setNext] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)

  const filter: AuditFilter = { actions, failed, q }
  const key = JSON.stringify(filter)
  useEffect(() => {
    const controller = new AbortController()
    getAudit(JSON.parse(key) as AuditFilter, undefined, controller.signal)
      .then((page) => {
        setEntries(page.entries)
        setNext(page.next_before)
        setLabels(page.actions)
        setError(null)
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [key])

  const older = async () => {
    if (!next) return
    setLoadingMore(true)
    try {
      const page = await getAudit(filter, next)
      setEntries((old) => [...(old ?? []), ...page.entries])
      setNext(page.next_before)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <Stack maw={1100}>
      <Title order={2}>Audit log</Title>
      <Text size="sm" c="dimmed">
        Every admin action: who did it, when, from which address, and how it went. Kept for 90 days.
      </Text>
      <Card withBorder>
        <Group align="flex-end">
          <MultiSelect
            label="Actions"
            placeholder={actions.length ? undefined : 'All'}
            data={Object.entries(labels).map(([value, label]) => ({ value, label }))}
            value={actions}
            onChange={setActions}
            searchable
            clearable
            miw={260}
          />
          <TextInput
            label="Search"
            placeholder="File name, slot, command…"
            value={text}
            onChange={(e) => setText(e.currentTarget.value)}
          />
          <Checkbox
            label="Only refused or failed"
            checked={failed}
            onChange={(e) => setFailed(e.currentTarget.checked)}
            mb={8}
          />
        </Group>
      </Card>
      {error && <Alert color="red">{error}</Alert>}
      {!entries && !error && <Loader size="sm" />}
      {entries && entries.length === 0 && <Text c="dimmed">Nothing recorded yet.</Text>}
      {entries && entries.length > 0 && (
        <Table.ScrollContainer minWidth={760}>
          <Table striped verticalSpacing="xs" aria-label="Audit log">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>When</Table.Th>
                <Table.Th>Who</Table.Th>
                <Table.Th>Action</Table.Th>
                <Table.Th>Result</Table.Th>
                <Table.Th>Detail</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {entries.map((entry) => (
                <Table.Tr key={entry.id}>
                  <Table.Td>
                    <Text size="sm">{new Date(entry.at).toLocaleString()}</Text>
                    {entry.client && (
                      <Text size="xs" c="dimmed">
                        {entry.client}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>{entry.actor ?? <Text c="dimmed">unknown</Text>}</Table.Td>
                  <Table.Td>
                    <Text size="sm">{entry.label}</Text>
                    {entry.target && (
                      <Text size="xs" c="dimmed">
                        {entry.target}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {entry.ok ? (
                      <Badge color="green" variant="light">
                        ok
                      </Badge>
                    ) : (
                      <Badge color="red" variant="light">
                        {entry.status}
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td maw={360}>
                    <Detail detail={entry.detail} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {next && (
        <Group>
          <Button variant="default" loading={loadingMore} onClick={older}>
            Older entries
          </Button>
        </Group>
      )}
    </Stack>
  )
}
