// The hire panel's two halves, behind one lazy chunk.
//
// Hiring is a rare action on a page the CEO opens constantly, and the gallery pulls in the
// crew-preview + template machinery — so it stays out of the entry bundle and only loads
// when the panel is actually opened. Default export so React.lazy can take it directly.
import { CrewPresets } from './crew-presets'
import { TemplateGallery } from './template-gallery'

export default function HirePanel() {
  return (
    <>
      <CrewPresets />
      <TemplateGallery />
    </>
  )
}
