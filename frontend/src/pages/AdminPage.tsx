import { Alert, Stack, Title } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useState } from 'react'
import { Apworlds } from '../components/Apworlds'
import { Archives } from '../components/Archives'
import { BackendStatus } from '../components/BackendStatus'
import { CurrentGame } from '../components/CurrentGame'
import { ServerFeed } from '../components/ServerFeed'
import { UploadLog } from '../components/UploadLog'
import { Uploads } from '../components/Uploads'

export function AdminPage() {
  // ARCHIVE and restore change the whole page: remount what shows the current game.
  const [version, setVersion] = useState(0)
  const changed = () => setVersion((v) => v + 1)
  return (
    <Stack maw={960} key={version}>
      <Title order={2}>Admin</Title>
      <Alert color="yellow" icon={<IconAlertTriangle />} title="No admin login in Alpha 1">
        Anyone who can reach this page can manage the server. Do not expose an Alpha 1 install to
        the internet.
      </Alert>
      <CurrentGame onChanged={changed} />
      <ServerFeed />
      <Uploads />
      <Apworlds />
      <UploadLog />
      <BackendStatus />
      <Archives onChanged={changed} />
    </Stack>
  )
}
