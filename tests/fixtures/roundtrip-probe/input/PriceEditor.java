package synthetic.pricepad;

import java.math.BigDecimal;

// Incomplete synthetic client. Not a specification of any real service.
public final class PriceEditor {
    public record Remote(long id, String amount, String description) {}
    public record Stored(int id, long minorUnits, String description) {}
    public interface Api {
        Remote fetch(long id);
        void update(long id, String amount, String description);
    }
    public interface Store {
        void put(Stored row);
        Stored get(int id);
        void markConflict(int id);
    }
    private final Api api;
    private final Store store;

    public PriceEditor(Api api, Store store) {
        this.api = api;
        this.store = store;
    }

    public void remember(Remote remote) {
        BigDecimal amount = new BigDecimal(remote.amount());
        int localId = Math.toIntExact(remote.id());
        long minorUnits = amount.movePointRight(2).longValueExact();
        store.put(new Stored(localId, minorUnits, remote.description()));
    }

    public void saveDescription(int id, String description) {
        Stored cached = store.get(id);
        BigDecimal previous = BigDecimal.valueOf(cached.minorUnits(), 2);
        Remote current = api.fetch(id);
        BigDecimal now = new BigDecimal(current.amount());
        if (!previous.equals(now)) {
            store.markConflict(id);
            return;
        }
        api.update(id, current.amount(), description);
        remember(api.fetch(id));
    }
}
