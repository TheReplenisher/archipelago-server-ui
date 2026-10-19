import { Anchor, Group, Stack, Text } from '@mantine/core'
import { IconDownload } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { listMyPatches, myPatchUrl, type PatchFile } from '../api/client'

const size = (bytes: number) =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`

/** The logged-in slot's own patch or mod files (#36), if its game has any. */
export function MyPatches() {
  const [patches, setPatches] = useState<PatchFile[]>([])

  useEffect(() => {
    const controller = new AbortController()
    listMyPatches(controller.signal)
      .then(setPatches)
      .catch(() => undefined)
    return () => controller.abort()
  }, [])

  if (patches.length === 0) return null
  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        Your patch {patches.length === 1 ? 'file' : 'files'}
      </Text>
      {patches.map((p) => (
        <Group key={p.file} gap="xs">
          <IconDownload size={16} />
          <Anchor href={myPatchUrl(p.file)} download size="sm">
            {p.file}
          </Anchor>
          <Text size="xs" c="dimmed">
            {size(p.size)}
          </Text>
        </Group>
      ))}
    </Stack>
  )
}
