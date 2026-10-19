import { Badge, Tooltip } from '@mantine/core'

/** Marks a file a player sent from the Player tab (#33), with their address on hover. */
export function UploadedBy({ by, from }: { by?: string; from?: string | null }) {
  if (by !== 'player') return null
  return (
    <Tooltip label={from ? `Uploaded by a player from ${from}` : 'Uploaded by a player'}>
      <Badge size="xs" variant="outline" color="gray" ml={6}>
        player
      </Badge>
    </Tooltip>
  )
}
