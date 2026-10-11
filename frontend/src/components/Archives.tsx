import { Alert, Anchor, Badge, Button, Card, Group, Modal, Stack, Table, Text } from '@mantine/core'
import { IconDownload } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import {
  ApiError,
  archiveDownloadUrl,
  archiveFileUrl,
  deleteArchive,
  getArchive,
  listArchives,
  restoreArchive,
  type Archive,
  type ArchiveDetail,
  type ArchiveList,
  type CurrentGameSummary,
  type RestoreChoice,
} from '../api/client'

function formatSize(bytes: number | null): string {
  if (bytes === null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function retentionText(list: ArchiveList): string {
  const { limit, max_count, max_size_mb, count, total_size } = list.retention
  const held = `${count} ${count === 1 ? 'archive' : 'archives'}, ${formatSize(total_size)}.`
  if (limit === 'count') return `${held} The newest ${max_count} are kept.`
  if (limit === 'size') return `${held} The newest are kept up to ${max_size_mb} MB in total.`
  return `${held} No limit is set (Settings).`
}

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '—')

/** One archive, read-only: slots, worlds, the generation log and every file. */
function BrowseModal({ id, onClose }: { id: number; onClose: () => void }) {
  const [detail, setDetail] = useState<ArchiveDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getArchive(id, controller.signal)
      .then(setDetail)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [id])

  return (
    <Modal opened onClose={onClose} title={`Archive of game #${id}`} size="lg">
      {error && <Alert color="red">{error}</Alert>}
      {detail && (
        <Stack gap="sm">
          <Text size="sm">
            Archived {when(detail.archived_at)} from <b>{detail.archived_from ?? 'unknown'}</b>
            {detail.seed_name ? `, seed ${detail.seed_name}` : ''}.
          </Text>
          <Text size="sm">
            <b>Slots:</b> {detail.slots.join(', ') || 'none'}
          </Text>
          {detail.worlds.length > 0 && (
            <Text size="sm">
              <b>Worlds:</b> {detail.worlds.join('; ')}
            </Text>
          )}
          {detail.generations.length > 0 && (
            <Text size="sm">
              <b>Generation log:</b>{' '}
              {detail.generations
                .map((g) =>
                  g.status === 'ok' ? `seed ${g.seed_name} ok` : `${g.status}: ${g.error_message}`,
                )
                .join('; ')}
            </Text>
          )}
          <Text size="sm" fw={500}>
            Files
          </Text>
          <Text size="xs" c="dimmed">
            The output zip holds the spoiler log and the patch files.
          </Text>
          <Table.ScrollContainer minWidth={360}>
            <Table verticalSpacing={4}>
              <Table.Tbody>
                {detail.files.map((f) => (
                  <Table.Tr key={f.path}>
                    <Table.Td>
                      <Anchor size="sm" href={archiveFileUrl(id, f.path)}>
                        {f.path}
                      </Anchor>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" c="dimmed" ta="right">
                        {formatSize(f.size)}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Stack>
      )}
    </Modal>
  )
}

/** Restore needs the current game out of the way, if it has anything in it. */
function CurrentGameModal({
  current,
  archiveId,
  busy,
  onChoose,
  onClose,
}: {
  current: CurrentGameSummary
  archiveId: number
  busy: boolean
  onChoose: (choice: RestoreChoice) => void
  onClose: () => void
}) {
  return (
    <Modal opened onClose={onClose} title={`Restore game #${archiveId}?`}>
      <Stack gap="sm">
        <Text size="sm">
          The current game #{current.id} is <b>{current.state}</b> with {current.slots}{' '}
          {current.slots === 1 ? 'slot' : 'slots'}. It has to make way first: archive it to keep it,
          or delete it for good.
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button color="red" variant="outline" loading={busy} onClick={() => onChoose('delete')}>
            Delete it, then restore
          </Button>
          <Button loading={busy} onClick={() => onChoose('archive')}>
            Archive it, then restore
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

/** Archived games: browse, download, restore, delete. */
export function Archives({ onChanged }: { onChanged: () => void }) {
  const [list, setList] = useState<ArchiveList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [version, setVersion] = useState(0)
  const [browsing, setBrowsing] = useState<number | null>(null)
  const [deleting, setDeleting] = useState<Archive | null>(null)
  const [restoring, setRestoring] = useState<{ id: number; current: CurrentGameSummary } | null>(
    null,
  )

  useEffect(() => {
    const controller = new AbortController()
    listArchives(controller.signal)
      .then(setList)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [version])

  const restore = async (id: number, choice: RestoreChoice | null) => {
    setBusy(true)
    setError(null)
    try {
      await restoreArchive(id, choice)
      setRestoring(null)
      onChanged()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'current-game' && e.detail?.current) {
        setRestoring({ id, current: e.detail.current as CurrentGameSummary })
      } else {
        setRestoring(null)
        setError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      setBusy(false)
      setVersion((v) => v + 1)
    }
  }

  const remove = async (id: number) => {
    setBusy(true)
    setError(null)
    try {
      await deleteArchive(id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setDeleting(null)
      setBusy(false)
      setVersion((v) => v + 1)
    }
  }

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={500}>Archives</Text>
          {list && list.archives.length > 0 && (
            <Badge variant="light" color="gray">
              {list.archives.length}
            </Badge>
          )}
        </Group>
        {list && (
          <Text size="sm" c="dimmed">
            {retentionText(list)}
          </Text>
        )}
        {error && (
          <Alert color="red" title="Something went wrong">
            {error}
          </Alert>
        )}
        {list && list.archives.length > 0 && (
          <Table.ScrollContainer minWidth={560}>
            <Table verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Game</Table.Th>
                  <Table.Th>Archived</Table.Th>
                  <Table.Th>Slots</Table.Th>
                  <Table.Th>Size</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.archives.map((a) => (
                  <Table.Tr key={a.id}>
                    <Table.Td>
                      #{a.id}
                      {a.seed_name ? ` · seed ${a.seed_name}` : ''}
                    </Table.Td>
                    <Table.Td>{when(a.archived_at)}</Table.Td>
                    <Table.Td>
                      <Text size="sm" lineClamp={1} title={a.slots.join(', ')}>
                        {a.slots.length}: {a.slots.join(', ')}
                      </Text>
                    </Table.Td>
                    <Table.Td>{formatSize(a.size)}</Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          onClick={() => setBrowsing(a.id)}
                        >
                          Browse
                        </Button>
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          component="a"
                          href={archiveDownloadUrl(a.id)}
                          leftSection={<IconDownload size={12} />}
                        >
                          Zip
                        </Button>
                        <Button
                          size="compact-xs"
                          variant="light"
                          loading={busy}
                          onClick={() => restore(a.id, null)}
                        >
                          Restore
                        </Button>
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          color="red"
                          onClick={() => setDeleting(a)}
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
      </Stack>
      {browsing !== null && <BrowseModal id={browsing} onClose={() => setBrowsing(null)} />}
      {restoring && (
        <CurrentGameModal
          current={restoring.current}
          archiveId={restoring.id}
          busy={busy}
          onChoose={(choice) => restore(restoring.id, choice)}
          onClose={() => setRestoring(null)}
        />
      )}
      {deleting && (
        <Modal opened onClose={() => setDeleting(null)} title={`Delete archive #${deleting.id}?`}>
          <Stack gap="sm">
            <Text size="sm">
              Its files and its upload and generation logs are deleted for good. Download the zip
              first to keep a copy.
            </Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setDeleting(null)}>
                Cancel
              </Button>
              <Button color="red" loading={busy} onClick={() => remove(deleting.id)}>
                Delete
              </Button>
            </Group>
          </Stack>
        </Modal>
      )}
    </Card>
  )
}
