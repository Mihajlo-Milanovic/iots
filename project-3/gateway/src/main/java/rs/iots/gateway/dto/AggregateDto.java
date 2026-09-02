package rs.iots.gateway.dto;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Agregacije nad izabranim poljem u zadatom vremenskom periodu")
public record AggregateDto(
        @Schema(example = "temperature") String field,
        @Schema(example = "b8:27:eb:bf:9d:51") String deviceId,
        double min, double max, double avg, double sum,
        @Schema(description = "Broj obuhvaćenih očitavanja", example = "412") long count) {}
