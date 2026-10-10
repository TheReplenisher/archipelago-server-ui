import { Alert, Badge, Button, Card, FileButton, Group, Stack, Table, Text } from '@mantine/core'
import { IconUpload } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { ReviewApworldModal } from './ReviewApworldModal'
import { listApworlds, uploadApworld, type Apworld, type ApworldStatus } from '../api/client'

const statusColor: Record<ApworldStatus, string> = {
  checking: 'blue',
  pending: 'orange',
  approved: 'green',
  rejected: 'red',
}

const statusLabel: Partial<Record<ApworldStatus, string>> = {
  pending: 'needs approval',
  approved: 'in library',
}

const POLL_MS = 1000

/** Custom apworlds: upload, the approval queue, and the library. */
export function Apworlds() {
  const [apworlds, setApworlds] = useState<Apworld[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [version, setVersion] = useState(0) // bump to reload the list
  const [reviewing, setReviewing] = useState<Apworld | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    listApworlds(controller.signal)
      .then(setApworlds)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [version])

  // While the worker import-tests a file, poll until it is done.
  const checking = apworlds.some((a) => a.status === 'checking')
  useEffect(() => {
    if (!checking) return
    const timer = setInterval(() => setVersion((v) => v + 1), POLL_MS)
    return () => clearInterval(timer)
  }, [checking])

  const upload = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      await uploadApworld(file)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      setVersion((v) => v + 1)
    }
  }

  const waiting = apworlds.filter((a) => a.status === 'pending').length

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={500}>Apworlds</Text>
          {waiting > 0 && (
            <Badge color="orange" variant="light">
              {waiting} waiting for approval
            </Badge>
          )}
        </Group>
        <FileButton onChange={(file) => file && upload(file)} accept=".apworld">
          {(props) => (
            <Button
              {...props}
              leftSection={<IconUpload size={16} />}
              loading={busy}
              w="fit-content"
            >
              Upload apworld
            </Button>
          )}
        </FileButton>
        {error && (
          <Alert color="red" title="Upload failed">
            {error}
          </Alert>
        )}
        {apworlds.length > 0 && (
          <Table.ScrollContainer minWidth={420}>
            <Table verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Apworld</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Reason</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {apworlds.map((a) => (
                  <Table.Tr key={a.id}>
                    <Table.Td>{a.game ? a.label : a.filename}</Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        <Badge color={statusColor[a.status]} variant="light">
                          {statusLabel[a.status] ?? a.status}
                        </Badge>
                        {a.replaces_builtin && (
                          <Badge color="orange" variant="outline">
                            replaces built-in
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      {a.status === 'rejected' && (
                        <Text size="sm" c="red">
                          {a.error_message}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Button
                        size="compact-xs"
                        variant={a.status === 'pending' ? 'light' : 'subtle'}
                        onClick={() => setReviewing(a)}
                      >
                        {a.status === 'pending' ? 'Review' : 'Details'}
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Stack>
      {reviewing && (
        <ReviewApworldModal
          apworld={reviewing}
          onClose={() => setReviewing(null)}
          onDone={() => {
            setReviewing(null)
            setVersion((v) => v + 1)
          }}
        />
      )}
    </Card>
  )
}
