<?php
namespace Emipro\Apichange\Model;

class UpdateStock implements \Emipro\Apichange\Api\Data\UpdateStockInterface
{
    protected $stock_id;
    protected $qty;
    protected $sku;

    /**
     * Gets the sku.
     *
     * @api
     * @return string
     */
    public function setIsInStock($stock_id)
    {
        $this->stock_id = $stock_id;
    }
    /**
     * Gets the sku.
     *
     * @api
     * @return string
     */
    public function getIsInStock()
    {
        return $this->stock_id;
    }
    /**
     * Gets the sku.
     *
     * @api
     * @return string
     */
    public function setQty($qty)
    {
        $this->qty = $qty;
    }
    /**
     * Gets the sku.
     *
     * @api
     * @return string
     */
    public function getQty()
    {
        return $this->qty;
    }

    /**
     * Gets the sku.
     *
     * @api
     * @return string
     */
    public function setSku($sku)
    {
        $this->sku = $sku;
    }
    /**
     * Gets the sku.
     *
     * @api
     * @return string
     */
    public function getSku()
    {
        return $this->sku;
    }
}
