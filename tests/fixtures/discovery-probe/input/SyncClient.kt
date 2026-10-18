package synthetic.trailshelf

// Synthetic, incomplete client excerpt for a workflow exercise; not a real App.
data class Entry(val id: String, val thumbnail: String?, val saved: Boolean)
data class Page(val entries: List<Entry>?, val cursor: String?)
interface Api {
    suspend fun page(after: String?, since: Long): Page
    suspend fun save(id: String, saved: Boolean)
}
interface Store {
    fun upsert(entries: List<Entry>)
    fun setSaved(id: String, saved: Boolean)
    fun markNeedsRetry(id: String)
    fun syncTime(): Long
    fun syncCompleted()
}
class SyncClient(private val api: Api, private val store: Store) {
    suspend fun refresh() {
        var cursor: String? = null
        do {
            val page = api.page(cursor, store.syncTime())
            val items = page.entries ?: error("missing entries")
            store.upsert(items)
            cursor = page.cursor?.takeIf { it.isNotEmpty() }
        } while (cursor != null)
        store.syncCompleted()
    }

    suspend fun save(entry: Entry, saved: Boolean) {
        store.setSaved(entry.id, saved)
        try {
            api.save(WireIds.toRemote(entry.id), saved)
        } catch (ex: Exception) {
            store.markNeedsRetry(entry.id)
        }
    }
}
