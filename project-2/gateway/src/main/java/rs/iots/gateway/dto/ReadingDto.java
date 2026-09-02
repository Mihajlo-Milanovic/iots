package rs.iots.gateway.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;

import java.time.Instant;

@Schema(description = "Očitavanje sa IoT senzora")
public record ReadingDto(
        @Schema(description = "Identifikator zapisa", example = "1", accessMode = Schema.AccessMode.READ_ONLY)
        Long id,

        @NotBlank
        @Schema(description = "Identifikator uređaja", example = "b8:27:eb:bf:9d:51")
        String deviceId,

        @Schema(description = "Vremenska oznaka očitavanja (ISO-8601 UTC)", example = "2020-07-12T00:01:34Z")
        Instant ts,

        @Schema(example = "22.7") Double temperature,
        @Schema(example = "51.0") Double humidity,
        @Schema(example = "0.0049") Double co,
        @Schema(example = "0.0204") Double smoke,
        @Schema(description = "Geografska širina", example = "44.8125") Double lat,
        @Schema(description = "Geografska dužina", example = "20.4612") Double lon
) {}
