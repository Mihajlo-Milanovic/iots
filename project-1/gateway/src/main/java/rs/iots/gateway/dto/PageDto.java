package rs.iots.gateway.dto;

import io.swagger.v3.oas.annotations.media.Schema;

import java.util.List;

@Schema(description = "Stranica rezultata pretrage")
public record PageDto(
        List<ReadingDto> items,
        @Schema(example = "1250") long total,
        @Schema(example = "0") int page,
        @Schema(example = "50") int size) {}
