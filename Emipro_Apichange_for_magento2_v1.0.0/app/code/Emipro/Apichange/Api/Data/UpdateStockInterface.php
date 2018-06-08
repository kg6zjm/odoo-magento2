<?php
namespace Emipro\Apichange\Api\Data;

interface UpdateStockInterface
{
    const IS_IN_STOCK = 'is_in_stock';
    const QTY = 'qty';
    const SKU = 'sku';

    /**
     * Gets the stock_id.
     *
     * @api
     * @return string
     */
    public function setIsInStock($stock_id);
    /**
     * Gets the stock_id.
     *
     * @api
     * @return string
     */
    public function getIsInStock();
    /**
     * Gets the qty.
     *
     * @api
     * @return string
     */
    public function setQty($qty);
    /**
     * Gets the qty.
     *
     * @api
     * @return string
     */
    public function getQty();
    /**
     * Gets the sku.
     *
     * @api
     * @return string
     */
    public function setSku($sku);
    /**
     * Gets the sku.
     *
     * @api
     * @return string
     */
    public function getSku();

}
