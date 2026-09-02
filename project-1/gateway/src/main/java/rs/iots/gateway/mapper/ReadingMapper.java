package rs.iots.gateway.mapper;

import com.google.protobuf.Timestamp;
import org.springframework.stereotype.Component;
import rs.iots.datamanager.v1.Reading;
import rs.iots.gateway.dto.ReadingDto;

import java.time.Instant;

@Component
public class ReadingMapper {

    public Reading toProto(ReadingDto dto) {
        Reading.Builder b = Reading.newBuilder()
                .setDeviceId(dto.deviceId() == null ? "" : dto.deviceId())
                .setTemperature(orZero(dto.temperature()))
                .setHumidity(orZero(dto.humidity()))
                .setCo(orZero(dto.co()))
                .setSmoke(orZero(dto.smoke()));
        if (dto.id() != null) {
            b.setId(dto.id());
        }
        b.setTs(toTimestamp(dto.ts() == null ? Instant.now() : dto.ts()));
        if (dto.lat() != null) {
            b.setLat(dto.lat());
        }
        if (dto.lon() != null) {
            b.setLon(dto.lon());
        }
        return b.build();
    }

    public ReadingDto toDto(Reading r) {
        return new ReadingDto(
                r.getId(),
                r.getDeviceId(),
                toInstant(r.getTs()),
                r.getTemperature(),
                r.getHumidity(),
                r.getCo(),
                r.getSmoke(),
                r.hasLat() ? r.getLat() : null,
                r.hasLon() ? r.getLon() : null);
    }

    public static Timestamp toTimestamp(Instant instant) {
        return Timestamp.newBuilder()
                .setSeconds(instant.getEpochSecond())
                .setNanos(instant.getNano())
                .build();
    }

    public static Instant toInstant(Timestamp ts) {
        return Instant.ofEpochSecond(ts.getSeconds(), ts.getNanos());
    }

    private static double orZero(Double v) {
        return v == null ? 0.0 : v;
    }
}
