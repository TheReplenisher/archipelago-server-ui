import { Anchor, Group, Stack, Table, Text } from '@mantine/core'
import { IconDownload } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { allPatchesUrl, listPatches, patchUrl, type PatchFile } from '../api/client'

/** Each slot's patch or mod file from the generated game, to download (admin only in
 * Alpha 1). Shown while the game is Generated or Running. */
export function PatchFiles() {
  const [patches, setPatches] = useState<PatchFile[]>([])

  useEffect(() => {
    const controller = new AbortController()
    listPatches(controller.signal)
      .then(setPatches)
      .catch(() => setPatches([]))
    return () => controller.abort()
  }, [])

  if (patches.length === 0) return null
  return (
    <Stack gap={4}>
      <Group justify="space-between">
        <Text fw={500} size="sm">
          Patch files
        </Text>
        <Anchor href={allPatchesUrl} size="sm">
          <Group gap={4}>
            <IconDownload size={14} />
            Download all
          </Group>
        </Anchor>
      </Group>
      <Table verticalSpacing={2}>
        <Table.Tbody>
          {patches.map((p) => (
            <Table.Tr key={p.file}>
              <Table.Td>
                <Text size="sm">{p.slot}</Text>
              </Table.Td>
              <Table.Td>
                <Anchor href={patchUrl(p.file)} size="sm">
                  {p.file}
                </Anchor>
              </Table.Td>
              <Table.Td>
                <Text size="sm" c="dimmed">
                  {Math.ceil(p.size / 1024)} KB
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  )
}
