import { Anchor } from '@mantine/core'
import { useState } from 'react'
import { UploadLogModal } from './UploadLogModal'
import type { UploadKind } from '../api/client'

/** A short error's code, linking to the upload's full log entry. */
export function ErrorCode({ kind, id, code }: { kind: UploadKind; id: number; code: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Anchor component="button" size="xs" c="dimmed" onClick={() => setOpen(true)}>
        {code}
      </Anchor>
      {open && <UploadLogModal kind={kind} id={id} onClose={() => setOpen(false)} />}
    </>
  )
}
