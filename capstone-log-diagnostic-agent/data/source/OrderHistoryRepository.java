package com.example.order;

public class OrderHistoryRepository {
    private final JdbcTemplate jdbcTemplate;

    public OrderHistoryRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<OrderHistory> findByCustomerReference(String customerReference) {
        String sql = "select id, order_date, total "
            + "from order_history "
            + "where customer_reference = ? "
            + "order by order_date desc";
        return jdbcTemplate.query(sql, orderHistoryMapper, customerReference);
    }
}
