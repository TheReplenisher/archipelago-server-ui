import { Alert, Badge, Code, Group, Loader, Modal, Stack, Table, Text } from '@mantine/core'
import { useEffect, useState } from 'react'
import { getUploadLog, type LogCheck, type LogDetail, type UploadKind } from '../api/client'

const checkColor: Record<LogCheck['status'], string> = {
  ok: 'green',
  failed: 'red',
  warning: 'orange',
  waiting: 'blue',
}

interface Props {
  kind: UploadKind
  id: number
  onClose: () => void
}

/** One upload log entry (DESIGN.md §4): who, when, hash, every check and its result, and
 * the worker's full error and traceback. Admin only; uploaders see the short error. */
export function UploadLogModal({ kind, id, onClose }: Props) {
  const [entry, setEntry] = useState<LogDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getUploadLog(kind, id, controller.signal)
      .then(setEntry)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [kind, id])

  return (
    <Modal opened onClose={onClose} title={`Upload log: ${kind}-${id}`} size="lg">
      {!entry ? (
        error ? (
          <Alert color="red">{error}</Alert>
        ) : (
          <Loader size="sm" />
        )
      ) : (
        <Stack>
          <Table verticalSpacing={4}>
            <Table.Tbody>
              <Table.Tr>
                <Table.Th w={140}>File</Table.Th>
                <Table.Td>
                  {entry.filename} ({entry.size} bytes)
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Th>Uploaded</Table.Th>
                <Table.Td>
                  {entry.uploaded_by}, {new Date(entry.uploaded_at).toLocaleString()}
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Th>SHA-256</Table.Th>
                <Table.Td>
                  <Code style={{ wordBreak: 'break-all' }}>{entry.sha256}</Code>
                </Table.Td>
              </Table.Tr>
              {entry.error_code && (
                <Table.Tr>
                  <Table.Th>Uploader saw</Table.Th>
                  <Table.Td>
                    {entry.error_message} <Code>{entry.error_code}</Code>
                  </Table.Td>
                </Table.Tr>
              )}
            </Table.Tbody>
          </Table>
          <Text fw={500} size="sm">
            Checks
          </Text>
          <Stack gap={6}>
            {entry.checks.map((c, i) => (
              <Stack key={i} gap={2}>
                <Group gap="xs" wrap="nowrap" align="flex-start">
                  <Badge color={checkColor[c.status]} variant="light" w={80}>
                    {c.status}
                  </Badge>
                  <Text size="sm">
                    <b>{c.name}</b>
                    {c.message && `: ${c.message}`}
                  </Text>
                </Group>
                {c.detail && (
                  <Code block mah={160} style={{ overflow: 'auto' }}>
                    {c.detail}
                  </Code>
                )}
              </Stack>
            ))}
          </Stack>
          {entry.job && (entry.job.traceback || entry.job.log_tail) && (
            <>
              <Text fw={500} size="sm">
                Worker job {entry.job.id} ({entry.job.status})
              </Text>
              {entry.job.traceback && (
                <Code block mah={240} style={{ overflow: 'auto' }}>
                  {entry.job.traceback}
                </Code>
              )}
              {entry.job.log_tail && (
                <Code block mah={160} style={{ overflow: 'auto' }}>
                  {entry.job.log_tail}
                </Code>
              )}
            </>
          )}
        </Stack>
      )}
    </Modal>
  )
}
