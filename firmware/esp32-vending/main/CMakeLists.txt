idf_component_register(
    SRCS
        "main.c"
        "../src/coin_acceptor.c"
        "../src/coin_offline_buffer.c"
        "../src/qr_payment.c"
    INCLUDE_DIRS
        "."
        "../include"
    REQUIRES
        common
)


