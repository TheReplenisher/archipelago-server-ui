import {
  Alert,
  Badge,
  Button,
  Card,
  FileButton,
  Group,
  MultiSelect,
  Stack,
  Table,
  Text,
} from '@mantine/core'
import { IconUpload } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { ErrorCode } from './ErrorCode'
import { FixNamesModal } from './FixNamesModal'
import {
  listApworlds,
  listUploads,
  listWorlds,
  removeUpload,
  uploadYaml,
  type Apworld,
  type Upload,
  type UploadStatus,
  type WorldLock,
} from '../api/client'

const statusColor: Record<UploadStatus, string> = {
  pending: 'blue',
  'needs-name': 'orange',
  accepted: 'green',
  rejected: 'red',
  removed: 'gray',
}

const statusLabel: Partial<Record<UploadStatus, string>> = {
  pending: 'checking',
  'needs-name': 'needs a name',
}

const POLL_MS = 1000

/** Player YAMLs for the current game: upload (admin only in Alpha 1), status, slots. */
export function Uploads() {
  const [uploads, setUploads] = useState<Upload[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [version, setVersion] = useState(0) // bump to reload the list
  const [fixing, setFixing] = useState<Upload | null>(null)
  const [library, setLibrary] = useState<Apworld[]>([])
  const [locks, setLocks] = useState<WorldLock[]>([])
  const [picked, setPicked] = useState<string[]>([])

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      listUploads(controller.signal),
      listApworlds(controller.signal),
      listWorlds(controller.signal),
    ])
      .then(([uploads, apworlds, worlds]) => {
        setUploads(uploads)
        // Custom versions of built-in games can't be used yet.
        setLibrary(apworlds.filter((a) => a.status === 'approved' && !a.replaces_builtin))
        setLocks(worlds)
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [version])

  // While a file is being checked, poll until the worker is done with it.
  const pending = uploads.some((u) => u.status === 'pending')
  useEffect(() => {
    if (!pending) return
    const timer = setInterval(() => setVersion((v) => v + 1), POLL_MS)
    return () => clearInterval(timer)
  }, [pending])

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      setVersion((v) => v + 1)
    }
  }

  const slotCount = uploads
    .filter((u) => u.status === 'accepted')
    .reduce((n, u) => n + u.slots.length, 0)

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={500}>Player YAMLs</Text>
          <Text size="sm" c="dimmed">
            {slotCount} {slotCount === 1 ? 'slot' : 'slots'}
          </Text>
        </Group>
        {locks.length > 0 && (
          <Group gap={4}>
            <Text size="sm" c="dimmed">
              World versions:
            </Text>
            {locks.map((l) => (
              <Badge key={l.world} variant="outline" color={l.apworld_id ? 'grape' : 'gray'}>
                {l.label}
              </Badge>
            ))}
          </Group>
        )}
        {library.length > 0 && (
          <MultiSelect
            label="Custom apworlds for this YAML"
            description="Games not picked use their locked version, else the official world"
            placeholder="Official worlds"
            data={library.map((a) => ({ value: String(a.id), label: a.label }))}
            value={picked}
            onChange={setPicked}
            clearable
            maw={480}
          />
        )}
        <FileButton
          onChange={(file) => file && act(() => uploadYaml(file, picked.map(Number)))}
          accept=".yaml,.yml,text/yaml"
        >
          {(props) => (
            <Button
              {...props}
              leftSection={<IconUpload size={16} />}
              loading={busy}
              w="fit-content"
            >
              Upload YAML
            </Button>
          )}
        </FileButton>
        {error && (
          <Alert color="red" title="Upload failed">
            {error}
          </Alert>
        )}
        {uploads.length > 0 && (
          <Table.ScrollContainer minWidth={420}>
            <Table verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>File</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Slots / reason</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {uploads.map((u) => (
                  <Table.Tr key={u.id}>
                    <Table.Td>{u.filename}</Table.Td>
                    <Table.Td>
                      <Badge color={statusColor[u.status]} variant="light">
                        {statusLabel[u.status] ?? u.status}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      {u.status === 'rejected' ? (
                        <Text size="sm" c="red">
                          {u.error_message}{' '}
                          {u.error_code && <ErrorCode kind="yaml" id={u.id} code={u.error_code} />}
                        </Text>
                      ) : u.status === 'needs-name' ? (
                        <Text size="sm" c="orange">
                          {u.name_problems.map((p) => p.message).join('; ')}
                        </Text>
                      ) : (
                        <Text size="sm">{u.slots.join(', ')}</Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {u.status === 'needs-name' && (
                        <Button size="compact-xs" variant="light" onClick={() => setFixing(u)}>
                          Fix name
                        </Button>
                      )}
                      {u.status === 'accepted' && (
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          color="red"
                          onClick={() => act(() => removeUpload(u.id))}
                        >
                          Remove
                        </Button>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Stack>
      {fixing && (
        <FixNamesModal
          upload={fixing}
          onClose={() => setFixing(null)}
          onDone={() => {
            setFixing(null)
            setVersion((v) => v + 1)
          }}
        />
      )}
    </Card>
  )
}
