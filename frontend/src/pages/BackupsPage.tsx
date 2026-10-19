import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
  FileButton,
  Group,
  Loader,
  Modal,
  Progress,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { IconDownload, IconUpload } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import {
  backupUrl,
  createBackup,
  deleteBackup,
  listBackups,
  restoreBackup,
  uploadBackup,
  type Backup,
  type BackupList,
} from '../api/client'

const POLL_MS = 1500

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

function size(bytes: number) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${Math.ceil(bytes / 1024)} KB`
}

/** Restore replaces everything: ask first, and say what it keeps. */
function RestoreModal({
  backup,
  onClose,
  onDone,
}: {
  backup: Backup
  onClose: () => void
  onDone: (text: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const restore = async () => {
    setBusy(true)
    setError(null)
    try {
      await restoreBackup(backup.name)
      onDone(`Restored ${backup.name}.`)
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal opened onClose={onClose} title="Restore this backup?">
      <Stack gap="sm">
        <Text size="sm">
          Everything is replaced with <b>{backup.name}</b> (
          {new Date(backup.created_at).toLocaleString()}): the current game, uploads, apworld
          library and settings
          {backup.archives ? ', and the archives' : '. Archives stay as they are'}.
        </Text>
        <Text size="sm">
          A backup of the current state is made first. Your admin password, logins and the audit log
          stay as they are now. Players are logged out of their slots.
        </Text>
        {error && <Alert color="red">{error}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button color="red" loading={busy} onClick={restore}>
            Restore
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

/** Backups of the database, library, current game and archives (#38). */
export function BackupsPage() {
  const [list, setList] = useState<BackupList | null>(null)
  const [archives, setArchives] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [restoring, setRestoring] = useState<Backup | null>(null)
  const [deleting, setDeleting] = useState<Backup | null>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [version, setVersion] = useState(0)
  const reload = () => setVersion((v) => v + 1)

  useEffect(() => {
    const controller = new AbortController()
    listBackups(controller.signal)
      .then(setList)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(message(e))
      })
    return () => controller.abort()
  }, [version])

  const making = list?.making ?? false
  useEffect(() => {
    if (!making) return
    const timer = setInterval(() => setVersion((v) => v + 1), POLL_MS)
    return () => clearInterval(timer)
  }, [making])

  const act = async (action: () => Promise<unknown>, done?: string) => {
    setError(null)
    setNotice(null)
    try {
      await action()
      if (done) setNotice(done)
    } catch (e) {
      setError(message(e))
    } finally {
      reload()
    }
  }

  const upload = (file: File) =>
    act(async () => {
      setProgress(0)
      try {
        await uploadBackup(file, setProgress)
      } finally {
        setProgress(null)
      }
    }, `Uploaded ${file.name}. Restore it from the list.`)

  return (
    <Stack maw={1000}>
      <Title order={2}>Backups</Title>
      <Text size="sm" c="dimmed">
        A backup holds the database (settings, uploads, logs), the apworld library, the current
        game's files and, if you like, the archives. They're kept on this server: download them to
        keep a copy somewhere else.
      </Text>
      <Card withBorder>
        <Group align="center">
          <Button loading={making} onClick={() => act(() => createBackup(archives))}>
            Make a backup
          </Button>
          <Checkbox
            label="Include the archives"
            checked={archives}
            onChange={(e) => setArchives(e.currentTarget.checked)}
          />
          <FileButton onChange={(file) => file && upload(file)} accept=".zip,application/zip">
            {(props) => (
              <Button
                {...props}
                variant="default"
                leftSection={<IconUpload size={16} />}
                disabled={progress !== null}
              >
                Upload a backup
              </Button>
            )}
          </FileButton>
        </Group>
        {making && (
          <Text size="sm" c="blue" mt="xs">
            Making a backup…
          </Text>
        )}
        {progress !== null && <Progress value={progress * 100} mt="sm" aria-label="Uploading" />}
      </Card>
      {notice && <Alert color="green">{notice}</Alert>}
      {error && <Alert color="red">{error}</Alert>}
      {!list && !error && <Loader size="sm" />}
      {list && list.backups.length === 0 && <Text c="dimmed">No backups yet.</Text>}
      {list && list.backups.length > 0 && (
        <Table.ScrollContainer minWidth={640}>
          <Table verticalSpacing="xs" aria-label="Backups">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Backup</Table.Th>
                <Table.Th>Made</Table.Th>
                <Table.Th>Size</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {list.backups.map((b) => (
                <Table.Tr key={b.name}>
                  <Table.Td>
                    <Group gap={6}>
                      <Anchor href={backupUrl(b.name)} download size="sm">
                        <IconDownload size={14} /> {b.name}
                      </Anchor>
                      {b.archives && (
                        <Badge size="xs" variant="light">
                          archives
                        </Badge>
                      )}
                      {!b.readable && (
                        <Badge size="xs" color="red" variant="light">
                          can't be restored
                        </Badge>
                      )}
                    </Group>
                    {b.app_version && (
                      <Text size="xs" c="dimmed">
                        app {b.app_version}
                        {b.archipelago_version ? ` · AP ${b.archipelago_version}` : ''} · {b.files}{' '}
                        files
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{new Date(b.created_at).toLocaleString()}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{size(b.size)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <Button
                        size="compact-xs"
                        variant="light"
                        disabled={!b.readable}
                        onClick={() => setRestoring(b)}
                      >
                        Restore
                      </Button>
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        color="red"
                        onClick={() => setDeleting(b)}
                      >
                        Delete
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {list && list.backups.length > 0 && (
        <Text size="xs" c="dimmed">
          {list.backups.length} backups, {size(list.total_size)} in all.
        </Text>
      )}
      {restoring && (
        <RestoreModal
          backup={restoring}
          onClose={() => setRestoring(null)}
          onDone={(text) => {
            setRestoring(null)
            setNotice(text)
            reload()
          }}
        />
      )}
      <Modal opened={deleting !== null} onClose={() => setDeleting(null)} title="Delete backup?">
        <Stack gap="sm">
          <Text size="sm">{deleting?.name} is deleted from this server for good.</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              color="red"
              onClick={() => {
                const name = deleting?.name
                setDeleting(null)
                if (name) void act(() => deleteBackup(name))
              }}
            >
              Delete
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
