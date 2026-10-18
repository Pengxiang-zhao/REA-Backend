package synthetic.trailshelf

import android.graphics.ImageDecoder
import java.nio.ByteBuffer

class ThumbnailReader(private val fetch: (String) -> ByteArray) {
    fun load(url: String) = ImageDecoder.decodeBitmap(
        ImageDecoder.createSource(ByteBuffer.wrap(fetch(url)))
    )
}
